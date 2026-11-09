from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import RequestContext
from ...audit import record_audit, record_outbox_event
from ...config import settings
from ...domain import BackpressureError
from ...models import DurableJob
from ...schemas import JobCreate
from .common import _hash_request
from .create import create_job_in_session

__all__ = [
    "_enforce_backlog_limit", "create_job",
]


async def _enforce_backlog_limit(
    session: AsyncSession, context: RequestContext, idempotency_key: str
) -> None:
    """Shed new work when the tenant's backlog is full. A duplicate key still returns the original.

    Only API and scheduler submissions are limited: webhook and reminder jobs are never dropped."""
    if not idempotency_key.strip():
        return
    existing = await session.scalar(
        select(DurableJob.id).where(
            DurableJob.tenant_id == context.tenant_id,
            DurableJob.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        return
    backlog = await session.scalar(
        select(func.count()).where(
            DurableJob.tenant_id == context.tenant_id,
            DurableJob.status.in_({"queued", "retryable"}),
        )
    )
    if int(backlog or 0) >= settings.max_queued_jobs_per_tenant:
        raise BackpressureError("The job backlog is full; retry later")


async def create_job(
    session: AsyncSession,
    context: RequestContext,
    payload: JobCreate,
    idempotency_key: str,
) -> DurableJob:
    hash_run_at = payload.run_at or datetime(1970, 1, 1, tzinfo=UTC)
    await _enforce_backlog_limit(session, context, idempotency_key)
    request_hash = _hash_request(
        job_type=payload.job_type,
        queue=payload.queue,
        priority=payload.priority,
        payload=payload.payload,
        run_at=hash_run_at,
        max_attempts=payload.max_attempts,
        backoff_seconds=min(payload.backoff_seconds, settings.job_max_backoff_seconds),
        timeout_seconds=payload.timeout_seconds,
    )
    job = await create_job_in_session(
        session,
        context,
        idempotency_key=idempotency_key,
        job_type=payload.job_type,
        queue=payload.queue,
        priority=payload.priority,
        payload=payload.payload,
        run_at=payload.run_at,
        max_attempts=payload.max_attempts,
        backoff_seconds=min(payload.backoff_seconds, settings.job_max_backoff_seconds),
        timeout_seconds=payload.timeout_seconds,
        request_hash_override=request_hash,
    )
    await record_audit(
        session,
        context,
        "job.created",
        "durable_job",
        job.id,
        details={"job_type": job.job_type, "queue": job.queue},
    )
    await record_outbox_event(
        session,
        context,
        "job.created",
        "durable_job",
        job.id,
        {"job_type": job.job_type, "queue": job.queue},
    )
    await session.commit()
    await session.refresh(job)
    return job
