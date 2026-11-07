from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.deps import RequestContext, require_permission
from ..db import get_session
from ..observability.service import (
    acknowledge_alert,
    collect_metrics,
    get_alert,
    list_alerts,
    list_events,
    list_metrics,
    resolve_alert,
    run_proactive_checks,
    summary,
)
from ..permissions import Permission
from ..schemas import (
    AlertDecision,
    AlertRead,
    MetricObservationRead,
    ObservabilitySummary,
    OperationalEventRead,
    ProactiveCheckResponse,
)

router = APIRouter()
SessionDependency = Annotated[AsyncSession, Depends(get_session)]
ReadContext = Annotated[
    RequestContext,
    Depends(require_permission(Permission.OBSERVABILITY_READ)),
]
ManageContext = Annotated[
    RequestContext,
    Depends(require_permission(Permission.OBSERVABILITY_MANAGE)),
]


@router.get("/observability/summary", response_model=ObservabilitySummary, tags=["observability"])
async def observability_summary_endpoint(
    session: SessionDependency,
    context: ReadContext,
    window_start: datetime | None = None,
    window_end: datetime | None = None,
) -> ObservabilitySummary:
    return await summary(
        session,
        context,
        window_start=window_start,
        window_end=window_end,
    )


@router.post(
    "/observability/metrics/collect",
    response_model=list[MetricObservationRead],
    status_code=status.HTTP_201_CREATED,
    tags=["observability"],
)
async def collect_metrics_endpoint(
    session: SessionDependency,
    context: ManageContext,
    window_start: datetime | None = None,
    window_end: datetime | None = None,
) -> list[MetricObservationRead]:
    observations = await collect_metrics(
        session,
        context,
        window_start=window_start,
        window_end=window_end,
    )
    return [MetricObservationRead.model_validate(item) for item in observations]


@router.get(
    "/observability/metrics",
    response_model=list[MetricObservationRead],
    tags=["observability"],
)
async def list_metrics_endpoint(
    session: SessionDependency,
    context: ReadContext,
    metric_key: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[MetricObservationRead]:
    observations = await list_metrics(
        session,
        context,
        metric_key=metric_key,
        limit=limit,
        offset=offset,
    )
    return [MetricObservationRead.model_validate(item) for item in observations]


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


@router.post(
    "/observability/alerts/{alert_id}/acknowledge",
    response_model=AlertRead,
    tags=["observability"],
)
async def acknowledge_alert_endpoint(
    alert_id: str,
    payload: AlertDecision,
    session: SessionDependency,
    context: ManageContext,
) -> AlertRead:
    alert = await acknowledge_alert(session, context, alert_id, payload)
    return AlertRead.model_validate(alert)


@router.post(
    "/observability/alerts/{alert_id}/resolve",
    response_model=AlertRead,
    tags=["observability"],
)
async def resolve_alert_endpoint(
    alert_id: str,
    payload: AlertDecision,
    session: SessionDependency,
    context: ManageContext,
) -> AlertRead:
    alert = await resolve_alert(session, context, alert_id, payload)
    return AlertRead.model_validate(alert)


@router.post(
    "/observability/proactive-checks/run",
    response_model=ProactiveCheckResponse,
    tags=["observability"],
)
async def run_proactive_checks_endpoint(
    session: SessionDependency,
    context: ManageContext,
) -> ProactiveCheckResponse:
    return await run_proactive_checks(session, context)
