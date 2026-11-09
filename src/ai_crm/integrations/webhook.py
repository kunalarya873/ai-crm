import hashlib
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..domain import (
    ConflictError,
    InvalidRequestError,
    NotFoundError,
)
from ..flags import require_capability, system_context
from ..models import (
    IntegrationConnection,
    WebhookEvent,
    utc_now,
)
from .contract import WebhookSignatureError
from .fixture import get_connector
from .webhook_enqueue import enqueue_received
from .webhook_parse import _parse_timestamp, parse_payload

__all__ = ["ingest_webhook"]


async def ingest_webhook(
    session: AsyncSession,
    provider_key: str,
    external_account_id: str,
    signature: str,
    raw_body: bytes,
    trace_id: str | None = None,
) -> tuple[WebhookEvent, bool]:
    """Return the stored event and whether this delivery was a duplicate."""
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
    await require_capability(
        session,
        system_context(connection.tenant_id, "system:webhook"),
        "connectors",
        operation="connector.webhook",
    )
    if connection.status in {"revoked", "disconnected"}:
        raise ConflictError(f"Connection is {connection.status} and does not accept webhooks")
    payload, event_id, event_type = parse_payload(raw_body)
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
        return existing, True

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
    connection_id, tenant_id = connection.id, connection.tenant_id
    event = WebhookEvent(
        connection_id=connection_id,
        provider_event_id=event_id,
        event_type=event_type,
        payload_hash=payload_hash,
        provider_timestamp=provider_timestamp,
        signature_valid=True,
        status="queued",
        payload=sanitized_payload,
    )
    session.add(event)
    try:
        await session.flush()
    except IntegrityError as error:
        await session.rollback()
        raced = await session.scalar(
            select(WebhookEvent).where(
                WebhookEvent.connection_id == connection_id,
                WebhookEvent.provider_event_id == event_id,
            )
        )
        if raced is None:
            raise
        if raced.payload_hash != payload_hash:
            raise ConflictError(
                "Webhook event id was replayed with a different payload"
            ) from error
        return raced, True
    await enqueue_received(
        session,
        event,
        connection_id=connection_id,
        tenant_id=tenant_id,
        provider_key=provider_key,
        event_type=event_type,
        trace_id=trace_id,
    )
    await session.commit()
    await session.refresh(event)
    return event, False
