import asyncio
import json
from dataclasses import dataclass
from typing import Any, Protocol

from ..domain import InvalidRequestError


class ProviderError(RuntimeError):
    """A provider could not produce a response."""


class ProviderTimeoutError(ProviderError):
    """A provider exceeded the gateway timeout."""


@dataclass(frozen=True)
class ProviderRequest:
    use_case: str
    prompt: str
    input_data: dict[str, Any]
    context_items: list[dict[str, Any]]
    max_output_chars: int


@dataclass(frozen=True)
class ProviderResponse:
    output: dict[str, Any]
    input_tokens: int
    output_tokens: int
    attempts: int = 1


@dataclass(frozen=True)
class ProviderTextResponse:
    text: str
    input_tokens: int
    output_tokens: int
    attempts: int = 1


class ModelProvider(Protocol):
    provider_key: str
    model_key: str

    async def generate_structured(self, request: ProviderRequest) -> ProviderResponse:
        ...

    async def generate_text(self, request: ProviderRequest) -> ProviderTextResponse:
        ...

    async def health(self) -> str:
        ...


class FixtureProvider:
    """Deterministic provider used for local development and contract tests."""

    provider_key = "fixture"
    model_key = "fixture-text-v1"

    def __init__(
        self,
        *,
        delay_seconds: float = 0,
        failure_message: str | None = None,
    ) -> None:
        self.delay_seconds = delay_seconds
        self.failure_message = failure_message

    async def generate_structured(self, request: ProviderRequest) -> ProviderResponse:
        if self.delay_seconds > 0:
            await asyncio.sleep(self.delay_seconds)
        if self.failure_message is not None:
            raise ProviderError(self.failure_message)
        output = self._build_output(request)
        output_tokens = max(1, len(str(output)) // 4)
        input_tokens = max(1, (len(request.prompt) + len(str(request.input_data))) // 4)
        return ProviderResponse(
            output=output,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    async def health(self) -> str:
        if self.failure_message is not None:
            raise ProviderError(self.failure_message)
        return "fixture provider ready"

    async def generate_text(self, request: ProviderRequest) -> ProviderTextResponse:
        structured = await self.generate_structured(request)
        text = json.dumps(structured.output, sort_keys=True)
        return ProviderTextResponse(
            text=text,
            input_tokens=structured.input_tokens,
            output_tokens=max(1, len(text) // 4),
        )

    def _build_output(self, request: ProviderRequest) -> dict[str, Any]:
        context_text = " ".join(item.get("text", "") for item in request.context_items).strip()
        if len(context_text) > request.max_output_chars:
            context_text = context_text[: request.max_output_chars].rstrip()
        evidence = request.input_data.get("evidence", [])
        if not isinstance(evidence, list):
            evidence = []
        if request.use_case == "customer_summary":
            points = [
                item.get("text", "").strip()
                for item in request.context_items
                if item.get("text", "").strip()
            ]
            return {
                "summary": context_text or "No authorised customer facts were available.",
                "key_points": points[:5],
                "confidence": 0.92 if points else 0.2,
                "uncertainty": [] if points else ["authorised_context_missing"],
                "evidence": evidence,
            }
        if request.use_case == "field_extraction":
            text = str(request.input_data.get("text") or context_text)
            fields = request.input_data.get("fields") or ["email", "phone", "company"]
            extracted: dict[str, Any] = {}
            missing: list[str] = []
            for field in fields:
                value = self._extract_field(field, text)
                extracted[field] = value
                if value is None:
                    missing.append(field)
            return {
                "fields": extracted,
                "missing_fields": missing,
                "confidence": 0.9 if extracted and not missing else 0.65,
                "uncertainty": ["requested_value_not_present"] if missing else [],
                "evidence": evidence,
            }
        if request.use_case == "next_step_recommendation":
            recommendation = (
                "Review the cited customer facts and confirm the next commitment with the owner."
            )
            return {
                "recommendation": recommendation,
                "rationale": context_text[:500] or "No authorised context was available.",
                "priority": "normal",
                "proposed_work_item": {
                    "item_type": "commitment",
                    "title": "Confirm the next customer commitment",
                    "requires_human_confirmation": True,
                },
                "confidence": 0.86 if context_text else 0.2,
                "uncertainty": [] if context_text else ["authorised_context_missing"],
                "evidence": evidence,
            }
        if request.use_case == "communication_draft":
            purpose = str(request.input_data.get("purpose") or "Follow up")
            recipient = str(request.input_data.get("recipient_name") or "there")
            channel = str(request.input_data.get("channel") or "email")
            return {
                "channel": channel,
                "subject": f"Follow-up: {purpose}" if channel == "email" else None,
                "body": (
                    f"Hi {recipient},\n\n"
                    f"I am following up regarding {purpose.lower()}. "
                    "Please review the details and let me know the next step.\n\n"
                    "Best,"
                ),
                "confidence": 0.82 if context_text else 0.35,
                "uncertainty": [] if context_text else ["draft_is_not_context_grounded"],
                "evidence": evidence,
            }
        if request.use_case == "workflow_plan":
            objective = str(
                request.input_data.get("objective")
                or "Complete the requested customer follow-up"
            )
            allowed = request.input_data.get("allowed_action_types") or [
                "create_work_item",
                "request_approval",
            ]
            if not isinstance(allowed, list):
                raise InvalidRequestError("allowed_action_types must be a list")
            actions = [
                {
                    "action_type": action,
                    "parameters": {"objective": objective},
                    "requires_approval": True,
                }
                for action in allowed
                if action in {"create_work_item", "request_approval"}
            ]
            return {
                "objective": objective,
                "steps": [
                    {
                        "step_key": "review_context",
                        "title": "Review authorised context",
                        "rationale": context_text[:300] or "Confirm the available evidence first.",
                        "requires_approval": True,
                    },
                    {
                        "step_key": "confirm_plan",
                        "title": "Confirm the proposed next steps",
                        "rationale": "A human must approve before any typed action is created.",
                        "requires_approval": True,
                    },
                ],
                "proposed_actions": actions,
                "confidence": 0.8 if context_text else 0.25,
                "uncertainty": [] if context_text else ["authorised_context_missing"],
                "evidence": evidence,
            }
        raise InvalidRequestError(f"Unsupported AI use case: {request.use_case}")

    @staticmethod
    def _extract_field(field: str, text: str) -> str | None:
        import re

        normalized = field.casefold()
        if normalized == "email":
            match = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", text)
            return match.group(0).rstrip(".,;:") if match else None
        if normalized in {"phone", "phone_number"}:
            match = re.search(r"(?:\+?\d[\d ()-]{7,}\d)", text)
            return match.group(0).strip() if match else None
        if normalized == "company":
            match = re.search(r"(?:company|account)\s*[:=-]\s*([A-Za-z0-9 &.-]+)", text, re.I)
            return match.group(1).strip() if match else None
        return None
