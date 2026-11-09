from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import RequestContext
from ...domain import InvalidRequestError, NotFoundError
from ...models import MetricObservation, OperationalAlert, OperationalEvent
from .guards import _require_read

__all__ = [
    "get_alert", "list_alerts", "list_events", "list_metrics",
]


async def list_metrics(
    session: AsyncSession,
    context: RequestContext,
    *,
    metric_key: str | None = None,
    limit: int,
    offset: int,
) -> list[MetricObservation]:
    _require_read(context)
    statement = select(MetricObservation).where(MetricObservation.tenant_id == context.tenant_id)
    if metric_key:
        statement = statement.where(MetricObservation.metric_key == metric_key)
    result = await session.scalars(
        statement.order_by(MetricObservation.created_at.desc()).offset(offset).limit(limit)
    )
    return list(result)


async def list_events(
    session: AsyncSession,
    context: RequestContext,
    *,
    event_type: str | None = None,
    trace_id: str | None = None,
    limit: int,
    offset: int,
) -> list[OperationalEvent]:
    _require_read(context)
    statement = select(OperationalEvent).where(OperationalEvent.tenant_id == context.tenant_id)
    if event_type:
        statement = statement.where(OperationalEvent.event_type == event_type)
    if trace_id:
        statement = statement.where(OperationalEvent.trace_id == trace_id)
    result = await session.scalars(
        statement.order_by(OperationalEvent.created_at.desc()).offset(offset).limit(limit)
    )
    return list(result)


async def list_alerts(
    session: AsyncSession,
    context: RequestContext,
    *,
    alert_status: str | None,
    alert_type: str | None,
    limit: int,
    offset: int,
) -> list[OperationalAlert]:
    _require_read(context)
    statement = select(OperationalAlert).where(OperationalAlert.tenant_id == context.tenant_id)
    if alert_status:
        if alert_status not in {"open", "acknowledged", "resolved", "suppressed"}:
            raise InvalidRequestError(f"Unsupported alert status: {alert_status}")
        statement = statement.where(OperationalAlert.status == alert_status)
    if alert_type:
        if alert_type not in {"system", "business"}:
            raise InvalidRequestError(f"Unsupported alert type: {alert_type}")
        statement = statement.where(OperationalAlert.alert_type == alert_type)
    result = await session.scalars(
        statement.order_by(OperationalAlert.created_at.desc()).offset(offset).limit(limit)
    )
    return list(result)


async def get_alert(
    session: AsyncSession,
    context: RequestContext,
    alert_id: str,
) -> OperationalAlert:
    _require_read(context)
    alert = await session.scalar(
        select(OperationalAlert).where(
            OperationalAlert.id == alert_id,
            OperationalAlert.tenant_id == context.tenant_id,
        )
    )
    if alert is None:
        raise NotFoundError("Operational alert not found")
    return alert
