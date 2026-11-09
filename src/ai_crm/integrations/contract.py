from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from ..domain import DomainError
from ..models import IntegrationConnection

__all__ = [
    "ActivityPage", "CanonicalActivity", "Connector", "ConnectorProviderError",
    "ExternalWriteResult", "SYNC_RETRY_BASE_SECONDS", "TRANSIENT_PROVIDER_CODES",
    "WebhookSignatureError",
]


SYNC_RETRY_BASE_SECONDS = 30


TRANSIENT_PROVIDER_CODES = frozenset({"timeout", "rate_limit", "provider_unavailable"})


class WebhookSignatureError(DomainError):
    pass


class ConnectorProviderError(DomainError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code


@dataclass(frozen=True)
class CanonicalActivity:
    provider_record_id: str
    kind: str
    subject: str
    body: str | None
    provider_updated_at: datetime
    source_url: str | None
    deleted: bool = False


@dataclass(frozen=True)
class ActivityPage:
    records: list[CanonicalActivity]
    next_cursor: str | None


@dataclass(frozen=True)
class ExternalWriteResult:
    provider_request_id: str
    response_metadata: dict[str, object]


class Connector(Protocol):
    provider_key: str

    async def test(self, connection: IntegrationConnection) -> None: ...

    async def refresh(self, connection: IntegrationConnection) -> datetime | None: ...

    async def list_activities(
        self,
        connection: IntegrationConnection,
        cursor: str | None,
    ) -> ActivityPage: ...

    async def write(
        self,
        connection: IntegrationConnection,
        operation: str,
        payload: dict[str, object],
        idempotency_key: str,
    ) -> ExternalWriteResult: ...

    def verify_webhook(self, raw_body: bytes, signature: str, secret_ref: str) -> bool: ...
