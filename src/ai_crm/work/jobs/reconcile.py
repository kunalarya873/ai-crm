from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import RequestContext
from ...audit import record_audit
from ...config import settings
from ...models import DurableJob, utc_now
from .claim import expired_condition
from .common import _aware, _ensure_worker
from .finish import _mark_reminder_failed
from .read import get_job

__all__ = [
    "heartbeat_job", "reconcile_expired_jobs",
]


async def reconcile_expired_jobs(
    session: AsyncSession,
    context: RequestContext,
) -> list[DurableJob]:
    now = utc_now()
    result = await session.scalars(
        select(DurableJob).where(
            DurableJob.tenant_id == context.tenant_id, expired_condition(now)
        )
    )
    jobs = list(result)
    for job in jobs:
        timeout_at = _aware(job.timeout_at)
        timed_out = timeout_at is not None and timeout_at <= now
        job.error_code = "job_timeout" if timed_out else "worker_lease_expired"
        job.error_detail = (
            "Job exceeded its execution timeout"
            if timed_out
            else "Worker lease expired before completion"
        )
        job.lease_owner = None
        job.lease_expires_at = None
        job.timeout_at = None
        if job.attempts < job.max_attempts:
            job.status = "retryable"
            delay = min(
                job.backoff_seconds * (2 ** max(job.attempts - 1, 0)),
                settings.job_max_backoff_seconds,
            )
            job.next_attempt_at = now + timedelta(seconds=delay)
        else:
            job.status = "dead_letter"
            job.next_attempt_at = None
        await _mark_reminder_failed(session, job)
        await record_audit(
            session,
            context,
            "job.expired",
            "durable_job",
            job.id,
            outcome="failed",
            reason=job.error_code,
            details={"status": job.status},
        )
    await session.commit()
    for job in jobs:
        await session.refresh(job)
    return jobs


async def heartbeat_job(
    session: AsyncSession,
    context: RequestContext,
    job_id: str,
    worker_id: str,
    lease_seconds: int,
) -> DurableJob:
    job = await get_job(session, context, job_id)
    _ensure_worker(job, worker_id)
    now = utc_now()
    job.heartbeat_at = now
    job.lease_expires_at = now + timedelta(seconds=lease_seconds)
    await session.commit()
    await session.refresh(job)
    return job
