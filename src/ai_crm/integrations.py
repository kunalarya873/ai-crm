import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .api.deps import RequestContext
from .audit import record_audit, record_outbox_event
from .config import settings
from .domain import (
    ConflictError,
    DomainError,
    InvalidRequestError,
    NotFoundError,
)
from .models import (
    Activity,
    ExternalWrite,
    IntegrationConnection,
    IntegrationRecordLink,
    IntegrationSyncRun,
    OutboxEvent,
    WebhookEvent,
    utc_now,
)
from .schemas import (
    ExternalWriteCreate,
    IntegrationConnectionCreate,
)


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


class FixtureConnector:
    provider_key = "fixture"

    async def test(self, connection: IntegrationConnection) -> None:
        if not connection.external_account_id:
            raise ConnectorProviderError("invalid_account", "Fixture account is missing")

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


async def create_connection(
    session: AsyncSession,
    context: RequestContext,
    payload: IntegrationConnectionCreate,
) -> IntegrationConnection:
    get_connector(payload.provider_key)
    existing = await session.scalar(
        select(IntegrationConnection).where(
            IntegrationConnection.provider_key == payload.provider_key,
            IntegrationConnection.external_account_id == payload.external_account_id,
        )
    )
    if existing is not None:
        raise ConflictError("This external account is already connected")
    connection = IntegrationConnection(
        tenant_id=context.tenant_id,
        provider_key=payload.provider_key,
        external_account_id=payload.external_account_id,
        scopes=payload.scopes,
        secret_ref=payload.secret_ref,
        configuration=payload.configuration,
    )
    session.add(connection)
    await session.flush()
    await record_audit(
        session,
        context,
        "integration.connection.created",
        "integration_connection",
        connection.id,
        details={"provider_key": connection.provider_key},
    )
    await record_outbox_event(
        session,
        context,
        "integration.connection.created",
        "integration_connection",
        connection.id,
        {"provider_key": connection.provider_key},
    )
    await session.commit()
    await session.refresh(connection)
    return connection


async def get_connection(
    session: AsyncSession,
    context: RequestContext,
    connection_id: str,
) -> IntegrationConnection:
    connection = await session.scalar(
        select(IntegrationConnection).where(
            IntegrationConnection.id == connection_id,
            IntegrationConnection.tenant_id == context.tenant_id,
        )
    )
    if connection is None:
        raise NotFoundError("Integration connection not found")
    return connection


async def list_connections(
    session: AsyncSession,
    context: RequestContext,
) -> list[IntegrationConnection]:
    result = await session.scalars(
        select(IntegrationConnection)
        .where(IntegrationConnection.tenant_id == context.tenant_id)
        .order_by(IntegrationConnection.created_at.desc())
    )
    return list(result)


async def test_connection(
    session: AsyncSession,
    context: RequestContext,
    connection_id: str,
) -> IntegrationConnection:
    connection = await get_connection(session, context, connection_id)
    connector = get_connector(connection.provider_key)
    await connector.test(connection)
    connection.status = "connected"
    connection.last_tested_at = utc_now()
    connection.last_error_code = None
    await record_audit(
        session,
        context,
        "integration.connection.tested",
        "integration_connection",
        connection.id,
    )
    await session.commit()
    await session.refresh(connection)
    return connection


async def set_connection_status(
    session: AsyncSession,
    context: RequestContext,
    connection_id: str,
    new_status: str,
) -> IntegrationConnection:
    connection = await get_connection(session, context, connection_id)
    if new_status not in {"disconnected", "revoked"}:
        raise InvalidRequestError("Unsupported connection status change")
    connection.status = new_status
    await record_audit(
        session,
        context,
        f"integration.connection.{new_status}",
        "integration_connection",
        connection.id,
    )
    await record_outbox_event(
        session,
        context,
        f"integration.connection.{new_status}",
        "integration_connection",
        connection.id,
    )
    await session.commit()
    await session.refresh(connection)
    return connection


async def list_sync_runs(
    session: AsyncSession,
    context: RequestContext,
    connection_id: str,
) -> list[IntegrationSyncRun]:
    await get_connection(session, context, connection_id)
    result = await session.scalars(
        select(IntegrationSyncRun)
        .where(IntegrationSyncRun.connection_id == connection_id)
        .order_by(IntegrationSyncRun.created_at.desc())
    )
    return list(result)


async def list_record_links(
    session: AsyncSession,
    context: RequestContext,
    connection_id: str,
) -> list[IntegrationRecordLink]:
    await get_connection(session, context, connection_id)
    result = await session.scalars(
        select(IntegrationRecordLink)
        .where(IntegrationRecordLink.connection_id == connection_id)
        .order_by(IntegrationRecordLink.last_seen_at.desc())
    )
    return list(result)


async def sync_connection(
    session: AsyncSession,
    context: RequestContext,
    connection_id: str,
    mode: str,
) -> IntegrationSyncRun:
    connection = await get_connection(session, context, connection_id)
    connection_is_writable(connection)
    if mode not in {"initial", "incremental", "reconcile"}:
        raise InvalidRequestError("Unsupported sync mode")
    active_run = await session.scalar(
        select(IntegrationSyncRun).where(
            IntegrationSyncRun.connection_id == connection_id,
            IntegrationSyncRun.status == "running",
            IntegrationSyncRun.lease_expires_at > utc_now(),
        )
    )
    if active_run is not None:
        raise ConflictError("A sync is already running for this connection")
    previous_cursor = None
    if mode != "initial":
        previous_cursor = await session.scalar(
            select(IntegrationSyncRun.cursor)
            .where(
                IntegrationSyncRun.connection_id == connection_id,
                IntegrationSyncRun.status == "succeeded",
            )
            .order_by(IntegrationSyncRun.created_at.desc())
            .limit(1)
        )

    run = IntegrationSyncRun(
        connection_id=connection.id,
        resource_type="activities",
        mode=mode,
        status="running",
        cursor=previous_cursor,
        lease_owner=context.actor_id,
        lease_expires_at=utc_now() + timedelta(seconds=settings.integration_lease_seconds),
        started_at=utc_now(),
        last_attempt_at=utc_now(),
    )
    session.add(run)
    await session.flush()
    connector = get_connector(connection.provider_key)
    try:
        page = await connector.list_activities(connection, run.cursor)
        for record in page.records:
            await _upsert_activity_record(session, connection, record)
        run.cursor = page.next_cursor
        run.records_processed = len(page.records)
        run.status = "succeeded"
        run.last_success_at = utc_now()
        run.finished_at = utc_now()
        run.lease_owner = None
        run.lease_expires_at = None
        await record_audit(
            session,
            context,
            "integration.sync.succeeded",
            "integration_sync_run",
            run.id,
            details={"records_processed": run.records_processed},
        )
        await record_outbox_event(
            session,
            context,
            "integration.sync.succeeded",
            "integration_sync_run",
            run.id,
            {"records_processed": run.records_processed, "cursor": run.cursor},
        )
    except ConnectorProviderError as error:
        run.status = "failed"
        run.failure_code = error.code
        run.failure_detail = str(error)
        run.retry_count += 1
        run.finished_at = utc_now()
        run.lease_owner = None
        run.lease_expires_at = None
    await session.commit()
    await session.refresh(run)
    return run


async def _upsert_activity_record(
    session: AsyncSession,
    connection: IntegrationConnection,
    record: CanonicalActivity,
) -> None:
    link = await session.scalar(
        select(IntegrationRecordLink).where(
            IntegrationRecordLink.connection_id == connection.id,
            IntegrationRecordLink.resource_type == "activity",
            IntegrationRecordLink.provider_record_id == record.provider_record_id,
        )
    )
    source_record_id = f"{connection.external_account_id}:{record.provider_record_id}"
    if link is None:
        activity = Activity(
            tenant_id=connection.tenant_id,
            kind=record.kind,
            subject=record.subject,
            body=record.body,
            event_at=record.provider_updated_at,
            ingested_at=utc_now(),
            actor_id="integration:fixture",
            source_system=connection.provider_key,
            source_record_id=source_record_id,
        )
        session.add(activity)
        await session.flush()
        link = IntegrationRecordLink(
            connection_id=connection.id,
            resource_type="activity",
            provider_record_id=record.provider_record_id,
            canonical_type="activity",
            canonical_id=activity.id,
            source_url=record.source_url,
            provider_updated_at=record.provider_updated_at,
            provenance={
                "provider_key": connection.provider_key,
                "external_account_id": connection.external_account_id,
            },
        )
        session.add(link)
    else:
        activity = await session.get(Activity, link.canonical_id)
        if activity is not None and (
            link.provider_updated_at is None
            or record.provider_updated_at > link.provider_updated_at
        ):
            activity.kind = record.kind
            activity.subject = record.subject
            activity.body = record.body
            activity.event_at = record.provider_updated_at
        link.source_url = record.source_url
        link.provider_updated_at = record.provider_updated_at
        link.deleted_at = utc_now() if record.deleted else None
    link.last_seen_at = utc_now()


async def create_external_write(
    session: AsyncSession,
    context: RequestContext,
    connection_id: str,
    payload: ExternalWriteCreate,
    idempotency_key: str,
) -> ExternalWrite:
    if not idempotency_key.strip():
        raise InvalidRequestError("Idempotency-Key header is required")
    connection = await get_connection(session, context, connection_id)
    connection_is_writable(connection)
    digest = request_hash(payload.payload)
    existing = await session.scalar(
        select(ExternalWrite).where(
            ExternalWrite.connection_id == connection.id,
            ExternalWrite.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_hash != digest:
            raise ConflictError("Idempotency-Key was reused with a different payload")
        return existing

    write = ExternalWrite(
        connection_id=connection.id,
        idempotency_key=idempotency_key,
        operation=payload.operation,
        request_hash=digest,
        status="pending",
        attempts=1,
    )
    session.add(write)
    await session.flush()
    connector = get_connector(connection.provider_key)
    try:
        result = await connector.write(
            connection,
            payload.operation,
            payload.payload,
            idempotency_key,
        )
        write.status = "succeeded"
        write.provider_request_id = result.provider_request_id
        write.response_metadata = result.response_metadata
    except ConnectorProviderError as error:
        write.status = "failed"
        write.last_error = error.code
    await record_audit(
        session,
        context,
        "integration.external_write.completed",
        "external_write",
        write.id,
        details={"status": write.status, "operation": write.operation},
    )
    await session.commit()
    await session.refresh(write)
    return write


async def ingest_webhook(
    session: AsyncSession,
    provider_key: str,
    external_account_id: str,
    signature: str,
    raw_body: bytes,
) -> WebhookEvent:
    connector = get_connector(provider_key)
    connection = await session.scalar(
        select(IntegrationConnection).where(
            IntegrationConnection.provider_key == provider_key,
            IntegrationConnection.external_account_id == external_account_id,
        )
    )
    if connection is None:
        raise NotFoundError("Integration connection not found")
    if not connector.verify_webhook(raw_body, signature, connection.secret_ref):
        raise WebhookSignatureError("Webhook signature is invalid")
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as error:
        raise InvalidRequestError("Webhook payload is not valid JSON") from error
    if not isinstance(payload, dict):
        raise InvalidRequestError("Webhook payload must be an object")
    event_id = payload.get("id")
    event_type = payload.get("type")
    if not isinstance(event_id, str) or not event_id.strip():
        raise InvalidRequestError("Webhook event id is required")
    if not isinstance(event_type, str) or not event_type.strip():
        raise InvalidRequestError("Webhook event type is required")
    payload_hash = hashlib.sha256(raw_body).hexdigest()
    existing = await session.scalar(
        select(WebhookEvent).where(
            WebhookEvent.connection_id == connection.id,
            WebhookEvent.provider_event_id == event_id,
        )
    )
    if existing is not None:
        if existing.payload_hash != payload_hash:
            raise ConflictError("Webhook event id was replayed with a different payload")
        existing.status = "duplicate"
        await session.commit()
        await session.refresh(existing)
        return existing

    provider_timestamp = _parse_timestamp(payload.get("timestamp"))
    if provider_timestamp and utc_now() - provider_timestamp > timedelta(
        seconds=settings.fixture_webhook_max_age_seconds
    ):
        raise InvalidRequestError("Webhook event is too old")
    sanitized_payload = {
        "id": event_id,
        "type": event_type,
        "timestamp": payload.get("timestamp"),
        "data": payload.get("data") if isinstance(payload.get("data"), dict) else {},
    }
    event = WebhookEvent(
        connection_id=connection.id,
        provider_event_id=event_id,
        event_type=event_type,
        payload_hash=payload_hash,
        provider_timestamp=provider_timestamp,
        signature_valid=True,
        status="queued",
        payload=sanitized_payload,
    )
    session.add(event)
    session.add(
        OutboxEvent(
            tenant_id=connection.tenant_id,
            event_type="integration.webhook.received",
            aggregate_type="webhook_event",
            aggregate_id=event_id,
            payload={"provider_key": provider_key, "event_type": event_type},
            correlation_id=event_id,
        )
    )
    await session.commit()
    await session.refresh(event)
    return event


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise InvalidRequestError("Webhook timestamp is invalid") from error
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
