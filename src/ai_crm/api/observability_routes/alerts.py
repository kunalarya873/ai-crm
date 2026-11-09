from datetime import datetime

from ...observability.service import (
    acknowledge_alert,
    resolve_alert,
    run_proactive_checks,
)
from ...observability.slo import evaluate_slos
from ...schemas import (
    AlertDecision,
    AlertRead,
    ProactiveCheckResponse,
    SloReport,
)
from .base import ManageContext, ReadContext, SessionDependency, router

__all__ = [
    "acknowledge_alert_endpoint", "observability_slos_endpoint", "resolve_alert_endpoint",
    "run_proactive_checks_endpoint",
]


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


@router.get("/observability/slos", response_model=SloReport, tags=["observability"])
async def observability_slos_endpoint(
    session: SessionDependency,
    context: ReadContext,
    window_start: datetime | None = None,
    window_end: datetime | None = None,
) -> SloReport:
    return await evaluate_slos(
        session, context, window_start=window_start, window_end=window_end
    )
