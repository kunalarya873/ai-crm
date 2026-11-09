from datetime import datetime

from fastapi import Query, status

from ...observability.service import (
    collect_metrics,
    list_metrics,
    summary,
)
from ...schemas import (
    MetricObservationRead,
    ObservabilitySummary,
)
from .base import ManageContext, ReadContext, SessionDependency, router

__all__ = [
    "collect_metrics_endpoint", "list_metrics_endpoint", "observability_summary_endpoint",
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
