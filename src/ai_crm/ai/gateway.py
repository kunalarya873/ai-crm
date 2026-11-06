import asyncio
from dataclasses import replace

from ..config import settings
from .providers import (
    ModelProvider,
    ProviderError,
    ProviderRequest,
    ProviderResponse,
    ProviderTextResponse,
    ProviderTimeoutError,
)

GenerationRequest = ProviderRequest
GenerationResult = ProviderResponse


class AIModelGateway:
    def __init__(
        self,
        provider: ModelProvider,
        *,
        timeout_seconds: float | None = None,
        max_attempts: int | None = None,
        retry_delay_seconds: float | None = None,
    ) -> None:
        self.provider = provider
        self.timeout_seconds = timeout_seconds or settings.ai_timeout_seconds
        self.max_attempts = max_attempts or settings.ai_max_attempts
        self.retry_delay_seconds = (
            settings.ai_retry_delay_seconds
            if retry_delay_seconds is None
            else retry_delay_seconds
        )

    async def generate_structured(self, request: GenerationRequest) -> GenerationResult:
        last_error: ProviderError | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                result = await asyncio.wait_for(
                    self.provider.generate_structured(request),
                    timeout=self.timeout_seconds,
                )
                return replace(result, attempts=attempt)
            except TimeoutError as error:
                last_error = ProviderTimeoutError("AI provider timed out")
                last_error.__cause__ = error
            except ProviderError as error:
                last_error = error
            if attempt < self.max_attempts and self.retry_delay_seconds > 0:
                await asyncio.sleep(self.retry_delay_seconds)
        assert last_error is not None
        raise last_error

    async def generate_text(self, request: GenerationRequest) -> ProviderTextResponse:
        last_error: ProviderError | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                result = await asyncio.wait_for(
                    self.provider.generate_text(request),
                    timeout=self.timeout_seconds,
                )
                return replace(result, attempts=attempt)
            except TimeoutError as error:
                last_error = ProviderTimeoutError("AI provider timed out")
                last_error.__cause__ = error
            except ProviderError as error:
                last_error = error
            if attempt < self.max_attempts and self.retry_delay_seconds > 0:
                await asyncio.sleep(self.retry_delay_seconds)
        assert last_error is not None
        raise last_error

    async def health(self) -> str:
        return await self.provider.health()
