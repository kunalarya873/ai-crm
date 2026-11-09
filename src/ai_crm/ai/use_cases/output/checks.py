import json
from typing import Any

from pydantic import BaseModel, ValidationError

from ....config import settings
from ....domain import InvalidRequestError
from ...prompts import PromptDefinition
from ...providers import ProviderTimeoutError
from ..constants import RESPONSE_MODELS
from ..context import _base_metadata
from .fallback import FallbackMixin

__all__ = [
    "OutputMixin",
]


class OutputMixin(FallbackMixin):
    @staticmethod
    def _estimate_cost(total_tokens: int, input_tokens: int) -> int:
        output_tokens = max(total_tokens - input_tokens, 0)
        input_units = (input_tokens + 999) // 1000
        output_units = (output_tokens + 999) // 1000
        return (
            input_units * settings.ai_cost_per_1k_input_micros
            + output_units * settings.ai_cost_per_1k_output_micros
        )

    @staticmethod
    def _failure_reason(error: Exception) -> str:
        if isinstance(error, ProviderTimeoutError):
            return "provider_timeout"
        if isinstance(error, ValidationError):
            return "structured_output_invalid"
        if isinstance(error, InvalidRequestError):
            return "output_policy_rejected"
        return "provider_error"

    @staticmethod
    def _enforce_output_policy(output: BaseModel, use_case: str) -> None:
        serialized = json.dumps(output.model_dump(mode="json"), default=str)
        if len(serialized) > settings.ai_max_output_chars:
            raise InvalidRequestError("AI output exceeds the configured length limit")
        forbidden_phrases = (
            "ignore previous instructions",
            "execute shell",
            "drop table",
            "delete all records",
        )
        if any(phrase in serialized.casefold() for phrase in forbidden_phrases):
            raise InvalidRequestError("AI output contains a forbidden command pattern")
        if use_case == "workflow_plan":
            for action in output.model_dump().get("proposed_actions", []):
                if action.get("requires_approval") is not True:
                    raise InvalidRequestError("Workflow actions must require approval")

    @staticmethod
    def _validate_output(
        use_case: str,
        run_id: str,
        prompt: PromptDefinition,
        context_assembly_id: str | None,
        provider_key: str,
        model_key: str,
        output: dict[str, Any],
        evidence: list[dict[str, Any]],
    ) -> BaseModel:
        model = RESPONSE_MODELS[use_case]
        output_data = dict(output)
        confidence_value = output_data.pop("confidence", 0.0)
        try:
            confidence = float(confidence_value)
        except (TypeError, ValueError) as error:
            raise InvalidRequestError("AI confidence must be numeric") from error
        metadata = _base_metadata(
            run_id,
            "succeeded",
            prompt,
            context_assembly_id,
            provider_key,
            model_key,
            confidence,
            list(output_data.pop("uncertainty", [])),
            output_data.pop("evidence", evidence) or evidence,
            None,
        )
        return model.model_validate({**output_data, **metadata})
