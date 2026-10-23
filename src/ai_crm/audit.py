from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession

from .models import AuditEvent, OutboxEvent

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
            details=details or {},
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
