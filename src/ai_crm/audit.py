from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import AuditEvent, OperationalEvent, OutboxEvent
from .observability.telemetry import redact_telemetry

if TYPE_CHECKING:
    from .api.deps import RequestContext


async def record_audit(
    session: AsyncSession,
    context: "RequestContext",
    action: str,
    entity_type: str,
    entity_id: str,
    *,
    outcome: str = "success",
    reason: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    dedup_key = f"{context.correlation_id}:{action}:{entity_type}:{entity_id}:{outcome}"
    safe_details = redact_telemetry(details or {})
    if not isinstance(safe_details, dict):
        safe_details = {}
    existing_event = await session.scalar(
        select(OperationalEvent).where(
            OperationalEvent.tenant_id == context.tenant_id,
            OperationalEvent.event_type == action,
            OperationalEvent.dedup_key == dedup_key,
        )
    )
    session.add(
        AuditEvent(
            tenant_id=context.tenant_id,
            actor_id=context.actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            outcome=outcome,
            reason=reason,
            correlation_id=context.correlation_id,
            details=safe_details,
        )
    )
    if existing_event is None:
        session.add(
            OperationalEvent(
                tenant_id=context.tenant_id,
                actor_id=context.actor_id,
                event_type=action,
                operation=action,
                resource_type=entity_type,
                resource_id=entity_id,
                outcome=outcome,
                correlation_id=context.correlation_id,
                trace_id=context.trace_id,
                dedup_key=dedup_key,
                payload=safe_details,
            )
        )


async def record_outbox_event(
    session: AsyncSession,
    context: "RequestContext",
    event_type: str,
    aggregate_type: str,
    aggregate_id: str,
    payload: dict[str, Any] | None = None,
) -> None:
    session.add(
        OutboxEvent(
            tenant_id=context.tenant_id,
            event_type=event_type,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            payload=payload or {},
            correlation_id=context.correlation_id,
        )
    )
