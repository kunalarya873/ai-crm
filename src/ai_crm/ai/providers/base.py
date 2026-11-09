from dataclasses import dataclass
from typing import Any, Protocol

__all__ = [
    "ModelProvider", "ProviderError", "ProviderRequest", "ProviderResponse",
    "ProviderTextResponse", "ProviderTimeoutError",
]


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
