from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import RequestContext
from ...audit import record_audit
from ...models import MetricObservation, OperationalAlert
from ...schemas import (
    MetricSummaryItem,
    ObservabilitySummary,
)
from .compute import _compute_metrics
from .guards import _require_manage, _require_read, _window

__all__ = [
    "collect_metrics", "summary",
]


async def collect_metrics(
    session: AsyncSession,
    context: RequestContext,
    *,
    window_start: datetime | None = None,
    window_end: datetime | None = None,
) -> list[MetricObservation]:
    _require_manage(context)
    start, end = _window(window_start, window_end)
    metrics = await _compute_metrics(session, context, start, end)
    observations: list[MetricObservation] = []
    for metric_key, value, unit, quality, dimensions in metrics:
        existing = await session.scalar(
            select(MetricObservation).where(
                MetricObservation.tenant_id == context.tenant_id,
                MetricObservation.metric_key == metric_key,
                MetricObservation.window_start == start,
                MetricObservation.window_end == end,
            )
        )
        if existing is None:
            existing = MetricObservation(
                tenant_id=context.tenant_id,
                metric_key=metric_key,
                value=value,
                unit=unit,
                quality=quality,
                dimensions=dimensions,
                source_event_ids=[],
                window_start=start,
                window_end=end,
            )
            session.add(existing)
        else:
            existing.value = value
            existing.unit = unit
            existing.quality = quality
            existing.dimensions = dimensions
        observations.append(existing)
    await record_audit(
        session,
        context,
        "observability.metrics.collected",
        "metric_observation",
        context.correlation_id,
        details={"metric_count": len(metrics), "window_start": start, "window_end": end},
    )
    await session.commit()
    for observation in observations:
        await session.refresh(observation)
    return observations


async def summary(
    session: AsyncSession,
    context: RequestContext,
    *,
    window_start: datetime | None = None,
    window_end: datetime | None = None,
) -> ObservabilitySummary:
    _require_read(context)
    start, end = _window(window_start, window_end)
    metrics = await _compute_metrics(session, context, start, end)
    items = [
        MetricSummaryItem(
            metric_key=metric_key,
            value=value,
            unit=unit,
            quality=quality,
            dimensions=dimensions,
        )
        for metric_key, value, unit, quality, dimensions in metrics
    ]
    open_alerts = await session.scalar(
        select(func.count(OperationalAlert.id)).where(
            OperationalAlert.tenant_id == context.tenant_id,
            OperationalAlert.status.in_({"open", "acknowledged"}),
        )
    )
    return ObservabilitySummary(
        window_start=start,
        window_end=end,
        metrics=items,
        open_alerts=int(open_alerts or 0),
        incomplete_metrics=[
            item.metric_key for item in items if item.quality != "complete"
        ],
    )
