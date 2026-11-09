from sqlalchemy.ext.asyncio import AsyncSession

from ..api.deps import RequestContext
from ..audit import record_audit
from ..models import OutboxEvent, WebhookEvent
from ..permissions import Permission

__all__ = ["enqueue_received"]


async def enqueue_received(
    session: AsyncSession,
    event: WebhookEvent,
    *,
    connection_id: str,
    tenant_id: str,
    provider_key: str,
    event_type: str,
    trace_id: str | None,
) -> None:
    from ..work.jobs import create_job_in_session

    event_id = event.provider_event_id
    webhook_context = RequestContext(
        tenant_id=tenant_id,
        actor_id="integration:webhook",
        role="system",
        correlation_id=event_id,
        permissions=frozenset({Permission.JOBS_MANAGE}),
        trace_id=trace_id,
    )
    job = await create_job_in_session(
        session,
        webhook_context,
        idempotency_key=f"webhook:{connection_id}:{event_id}",
        job_type="integration.webhook",
        queue="default",
        payload={"event_id": event.id},
    )
    await record_audit(
        session,
        webhook_context,
        "integration.webhook.received",
        "webhook_event",
        event.id,
        details={"event_type": event_type, "job_id": job.id},
    )
    session.add(
        OutboxEvent(
            tenant_id=tenant_id,
            event_type="integration.webhook.received",
            aggregate_type="webhook_event",
            aggregate_id=event_id,
            payload={"provider_key": provider_key, "event_type": event_type},
            correlation_id=event_id,
        )
    )
