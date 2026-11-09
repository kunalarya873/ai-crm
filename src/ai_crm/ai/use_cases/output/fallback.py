from typing import Any

from pydantic import BaseModel

from ....schemas import (
    AICommunicationDraftResponse,
    AICustomerSummaryResponse,
    AIFieldExtractionResponse,
    AINextStepResponse,
    AIWorkflowPlanResponse,
)
from ...prompts import PromptDefinition
from ..context import _base_metadata

__all__ = [
    "FallbackMixin",
]


class FallbackMixin:
    @staticmethod
    def _fallback_output(
        use_case: str,
        run_id: str,
        prompt: PromptDefinition,
        context_assembly_id: str | None,
        provider_key: str,
        model_key: str,
        *,
        reason: str,
        evidence: list[dict[str, Any]],
    ) -> BaseModel:
        metadata = _base_metadata(
            run_id,
            "fallback",
            prompt,
            context_assembly_id,
            provider_key,
            model_key,
            0.0,
            [reason],
            evidence,
            reason,
        )
        if use_case == "customer_summary":
            return AICustomerSummaryResponse(
                **metadata,
                summary="I could not produce a grounded customer summary from authorised evidence.",
                key_points=[],
            )
        if use_case == "field_extraction":
            return AIFieldExtractionResponse(
                **metadata,
                fields={},
                missing_fields=[],
            )
        if use_case == "next_step_recommendation":
            return AINextStepResponse(
                **metadata,
                recommendation="Review the customer record manually before choosing a next step.",
                rationale=(
                    "The available authorised evidence is insufficient for a grounded "
                    "recommendation."
                ),
                priority="normal",
                proposed_work_item=None,
            )
        if use_case == "communication_draft":
            return AICommunicationDraftResponse(
                **metadata,
                channel="email",
                subject=None,
                body=(
                    "No grounded draft is available. Review the customer record and write "
                    "the message manually."
                ),
            )
        return AIWorkflowPlanResponse(
            **metadata,
            objective="",
            steps=[],
            proposed_actions=[],
        )
