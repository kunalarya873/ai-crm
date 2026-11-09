from fastapi import Query

from ...observability.service import (
    get_alert,
    list_alerts,
    list_events,
)
from ...schemas import AlertRead, OperationalEventRead
from .base import ReadContext, SessionDependency, router

__all__ = [
    "get_alert_endpoint", "list_alerts_endpoint", "list_events_endpoint",
]


@router.get(
    "/observability/events",
    response_model=list[OperationalEventRead],
    tags=["observability"],
)
async def list_events_endpoint(
    session: SessionDependency,
    context: ReadContext,
    event_type: str | None = None,
    trace_id: str | None = Query(default=None, min_length=32, max_length=32),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[OperationalEventRead]:
    events = await list_events(
        session,
        context,
        event_type=event_type,
        trace_id=trace_id,
        limit=limit,
        offset=offset,
    )
    return [OperationalEventRead.model_validate(item) for item in events]


@router.get("/observability/alerts", response_model=list[AlertRead], tags=["observability"])
async def list_alerts_endpoint(
    session: SessionDependency,
    context: ReadContext,
    alert_status: str | None = Query(default=None, alias="status"),
    alert_type: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[AlertRead]:
    alerts = await list_alerts(
        session,
        context,
        alert_status=alert_status,
        alert_type=alert_type,
        limit=limit,
        offset=offset,
    )
    return [AlertRead.model_validate(alert) for alert in alerts]


@router.get("/observability/alerts/{alert_id}", response_model=AlertRead, tags=["observability"])
async def get_alert_endpoint(
    alert_id: str,
    session: SessionDependency,
    context: ReadContext,
) -> AlertRead:
    return AlertRead.model_validate(await get_alert(session, context, alert_id))
