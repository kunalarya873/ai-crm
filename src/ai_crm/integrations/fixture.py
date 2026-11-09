import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta

from ..domain import (
    InvalidRequestError,
)
from ..models import (
    IntegrationConnection,
    utc_now,
)
from .contract import (
    ActivityPage,
    CanonicalActivity,
    Connector,
    ConnectorProviderError,
    ExternalWriteResult,
)

__all__ = [
    "CONNECTORS", "FixtureConnector", "MAX_WEBHOOK_EVENT_ID_LENGTH", "connection_is_writable",
    "get_connector", "request_hash",
]


class FixtureConnector:
    provider_key = "fixture"

    async def test(self, connection: IntegrationConnection) -> None:
        if not connection.external_account_id:
            raise ConnectorProviderError("invalid_account", "Fixture account is missing")

    async def refresh(self, connection: IntegrationConnection) -> datetime | None:
        failure = connection.configuration.get("refresh_failure")
        if failure:
            raise ConnectorProviderError(str(failure), "Fixture configured to fail token refresh")
        return utc_now() + timedelta(hours=1)

    async def list_activities(
        self,
        connection: IntegrationConnection,
        cursor: str | None,
    ) -> ActivityPage:
        if cursor == "done":
            return ActivityPage(records=[], next_cursor="done")
        return ActivityPage(
            records=[
                CanonicalActivity(
                    provider_record_id="fixture-activity-1",
                    kind="note",
                    subject="Fixture activity",
                    body="A deterministic activity from the fixture connector.",
                    provider_updated_at=datetime(2026, 1, 1, tzinfo=UTC),
                    source_url=(
                        "https://fixture.invalid/accounts/"
                        f"{connection.external_account_id}/activities/fixture-activity-1"
                    ),
                )
            ],
            next_cursor="done",
        )

    async def write(
        self,
        connection: IntegrationConnection,
        operation: str,
        payload: dict[str, object],
        idempotency_key: str,
    ) -> ExternalWriteResult:
        if operation not in {"activity.create"}:
            raise ConnectorProviderError(
                "unsupported_operation",
                "Fixture operation is not supported",
            )
        configured_failure = connection.configuration.get("write_failure")
        if configured_failure in {"timeout", "uncertain", "rate_limit"}:
            raise ConnectorProviderError(
                str(configured_failure),
                f"Fixture configured to simulate {configured_failure}",
            )
        return ExternalWriteResult(
            provider_request_id=f"fixture-request-{idempotency_key}",
            response_metadata={
                "provider": self.provider_key,
                "operation": operation,
                "accepted_fields": sorted(payload),
            },
        )

    def verify_webhook(self, raw_body: bytes, signature: str, secret_ref: str) -> bool:
        expected = hmac.new(secret_ref.encode(), raw_body, hashlib.sha256).hexdigest()
        provided = signature.removeprefix("sha256=").strip()
        return hmac.compare_digest(expected, provided)


CONNECTORS: dict[str, Connector] = {"fixture": FixtureConnector()}


MAX_WEBHOOK_EVENT_ID_LENGTH = 100


def get_connector(provider_key: str) -> Connector:
    connector = CONNECTORS.get(provider_key)
    if connector is None:
        raise InvalidRequestError(f"Provider '{provider_key}' is not configured")
    return connector


def request_hash(payload: dict[str, object]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def connection_is_writable(connection: IntegrationConnection) -> None:
    if connection.status != "connected":
        raise InvalidRequestError("Integration connection is not connected")
    if connection.token_expires_at and connection.token_expires_at <= utc_now():
        raise InvalidRequestError("Integration connection has expired")
