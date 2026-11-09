from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import RequestContext
from ...audit import record_audit
from ...domain import ConflictError
from ...models import OperationalAlert, utc_now
from ...schemas import AlertDecision
from .guards import _require_manage
from .queries import get_alert

__all__ = [
    "acknowledge_alert", "resolve_alert",
]


async def acknowledge_alert(
    session: AsyncSession,
    context: RequestContext,
    alert_id: str,
    payload: AlertDecision,
) -> OperationalAlert:
    _require_manage(context)
    alert = await get_alert(session, context, alert_id)
    if alert.status == "resolved":
        raise ConflictError("Resolved alerts cannot be acknowledged")
    alert.status = "acknowledged"
    alert.acknowledged_by = context.actor_id
    alert.acknowledged_at = utc_now()
    await record_audit(
        session,
        context,
        "observability.alert.acknowledged",
        "operational_alert",
        alert.id,
        details={"note": payload.note},
    )
    await session.commit()
    await session.refresh(alert)
    return alert


async def resolve_alert(
    session: AsyncSession,
    context: RequestContext,
    alert_id: str,
    payload: AlertDecision,
) -> OperationalAlert:
    _require_manage(context)
    alert = await get_alert(session, context, alert_id)
    if alert.status == "resolved":
        return alert
    alert.status = "resolved"
    alert.resolved_by = context.actor_id
    alert.resolved_at = utc_now()
    alert.resolution_note = payload.note
    await record_audit(
        session,
        context,
        "observability.alert.resolved",
        "operational_alert",
        alert.id,
        details={"note": payload.note},
    )
    await session.commit()
    await session.refresh(alert)
    return alert
