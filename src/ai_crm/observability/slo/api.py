from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import RequestMetricBucket
from ..requests import LATENCY_BOUNDS_MS

__all__ = ["_api_slis"]

LATENCY_COLUMNS = [f"le_{bound}" for bound in LATENCY_BOUNDS_MS] + ["le_inf"]


async def _api_slis(
    session: AsyncSession, tenant_id: str, start: datetime, end: datetime
) -> tuple[float | None, float | None, float | None, dict]:
    """Availability, 5xx rate and p95 latency from request buckets, summed over processes.
    Kill-switch 503s ("disabled") are neither errors nor requests for these ratios. The p95 is
    the upper bound of the histogram bucket holding the 95th percentile."""
    columns = [getattr(RequestMetricBucket, name) for name in LATENCY_COLUMNS]
    rows = (
        await session.execute(
            select(
                RequestMetricBucket.status_class,
                func.sum(RequestMetricBucket.count),
                *(func.sum(column) for column in columns),
            )
            .where(
                RequestMetricBucket.tenant_id == tenant_id,
                RequestMetricBucket.bucket_start >= start.replace(second=0, microsecond=0),
                RequestMetricBucket.bucket_start <= end,
            )
            .group_by(RequestMetricBucket.status_class)
        )
    ).all()
    rows = [tuple(row) for row in rows]
    counts = {row[0]: int(row[1] or 0) for row in rows}
    platform_5xx = int(
        await session.scalar(
            select(func.coalesce(func.sum(RequestMetricBucket.count), 0)).where(
                RequestMetricBucket.tenant_id == "",
                RequestMetricBucket.status_class == "5xx",
                RequestMetricBucket.bucket_start >= start.replace(second=0, microsecond=0),
                RequestMetricBucket.bucket_start <= end,
            )
        )
        or 0
    )
    served = {name: count for name, count in counts.items() if name != "disabled"}
    total = sum(served.values())
    detail = {
        "requests": total,
        "by_status_class": counts,
        # 5xx before a request's tenant was verified (e.g. the membership lookup failing) cannot
        # be attributed to a tenant; this is the platform-wide count for the window.
        "platform_5xx_requests": platform_5xx,
    }
    if not total:
        return None, None, None, detail
    errors = served.get("5xx", 0)
    histogram = [0] * len(LATENCY_COLUMNS)
    for row in rows:
        if row[0] != "disabled":
            histogram = [a + int(b or 0) for a, b in zip(histogram, row[2:])]
    threshold, running = 0.95 * sum(histogram), 0
    p95 = float(LATENCY_BOUNDS_MS[-1])
    for index, bucket_count in enumerate(histogram):
        running += bucket_count
        if running >= threshold:
            if index < len(LATENCY_BOUNDS_MS):
                p95 = float(LATENCY_BOUNDS_MS[index])
            else:
                detail["p95_overflow"] = True
            break
    return 1 - errors / total, errors / total, p95, detail
