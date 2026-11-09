from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import (
    DurableJob,
)
from ..service import _as_utc

__all__ = [
    "_job_success", "_queue_age",
]


async def _queue_age(session: AsyncSession, tenant_id: str, now: datetime) -> tuple[float, dict]:
    """Oldest work that is ready now: waiting jobs, plus running jobs whose lease has expired
    (a crashed worker), which the lease-reclaim logic also treats as ready."""
    waiting = await session.scalar(
        select(func.min(DurableJob.run_at)).where(
            DurableJob.tenant_id == tenant_id,
            DurableJob.status.in_({"queued", "retryable"}),
            DurableJob.run_at <= now,
        )
    )
    abandoned = await session.scalar(
        select(func.min(DurableJob.lease_expires_at)).where(
            DurableJob.tenant_id == tenant_id,
            DurableJob.status == "running",
            DurableJob.lease_expires_at <= now,
        )
    )
    candidates = [_as_utc(value) for value in (waiting, abandoned) if value is not None]
    if not candidates:
        return 0.0, {"ready_jobs": 0}
    oldest = min(c for c in candidates if c is not None)
    age = max((now - oldest).total_seconds(), 0.0)
    detail = {"oldest_ready_job_at": oldest.isoformat(), "abandoned_leases": abandoned is not None}
    return age, detail


async def _job_success(
    session: AsyncSession, tenant_id: str, start: datetime, end: datetime
) -> tuple[float | None, dict]:
    rows = await session.execute(
        select(DurableJob.status, func.count())
        .where(
            DurableJob.tenant_id == tenant_id,
            func.coalesce(DurableJob.completed_at, DurableJob.updated_at) >= start,
            func.coalesce(DurableJob.completed_at, DurableJob.updated_at) <= end,
            DurableJob.status.in_({"succeeded", "failed", "dead_letter"}),
        )
        .group_by(DurableJob.status)
    )
    counts = {status: count for status, count in rows.all()}
    finished = sum(counts.values())
    if not finished:
        return None, {"finished_jobs": 0}
    return counts.get("succeeded", 0) / finished, {"finished_jobs": finished, **counts}
