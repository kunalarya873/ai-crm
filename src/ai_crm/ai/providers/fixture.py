import asyncio
import json
from typing import Any

from ...domain import InvalidRequestError
from .base import ProviderError, ProviderRequest, ProviderResponse, ProviderTextResponse
from .outputs import OUTPUT_BUILDERS

__all__ = [
    "FixtureProvider",
]


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
        builder = OUTPUT_BUILDERS.get(request.use_case)
        if builder is None:
            raise InvalidRequestError(f"Unsupported AI use case: {request.use_case}")
        return builder(request, context_text, evidence)
