from collections.abc import Collection
from dataclasses import replace
from datetime import datetime, timedelta
from typing import cast

from sqlalchemy import ColumnElement, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import RequestContext
from ...audit import record_audit
from ...domain import InvalidRequestError
from ...models import DurableJob, utc_now

__all__ = [
    "CLAIM_ATTEMPTS", "claim_next_job", "expired_condition", "ready_condition",
]


CLAIM_ATTEMPTS = 3


def ready_condition(now: datetime) -> ColumnElement[bool]:
    """Queued or retryable jobs that are due. Shared by claiming and the worker's discovery."""
    return (
        DurableJob.status.in_({"queued", "retryable"})
        & (DurableJob.run_at <= now)
        & or_(DurableJob.next_attempt_at.is_(None), DurableJob.next_attempt_at <= now)
    )


def expired_condition(now: datetime) -> ColumnElement[bool]:
    """Running jobs whose lease or timeout has passed. Shared by reconciliation and discovery."""
    return (DurableJob.status == "running") & or_(
        DurableJob.lease_expires_at <= now, DurableJob.timeout_at <= now
    )


async def claim_next_job(
    session: AsyncSession,
    context: RequestContext,
    *,
    queue: str,
    worker_id: str,
    lease_seconds: int,
    job_types: Collection[str] | None = None,
) -> DurableJob | None:
    if not worker_id.strip():
        raise InvalidRequestError("worker_id is required")
    now = utc_now()
    ready = ready_condition(now) | (
        (DurableJob.status == "running") & (DurableJob.lease_expires_at <= now)
    )
    statement = (
        select(DurableJob)
        .where(
            DurableJob.tenant_id == context.tenant_id,
            DurableJob.queue == queue,
            ready,
            *([DurableJob.job_type.in_(job_types)] if job_types is not None else []),
        )
        .order_by(DurableJob.priority.desc(), DurableJob.run_at, DurableJob.created_at)
        .limit(1)
    )
    job: DurableJob | None = None
    for _ in range(CLAIM_ATTEMPTS):
        job = await session.scalar(statement)
        if job is None:
            return None
        previous_status, previous_attempts = job.status, job.attempts
        values: dict[str, object] = {
            "status": "running",
            "lease_owner": worker_id,
            "lease_expires_at": now + timedelta(seconds=lease_seconds),
            "heartbeat_at": now,
            "timeout_at": now + timedelta(seconds=job.timeout_seconds),
            "started_at": job.started_at or now,
            "attempts": previous_attempts + 1,
            "updated_at": now,
        }
        if previous_status == "running":
            values["error_code"] = "worker_lease_expired"
            values["error_detail"] = "Previous worker lease expired before completion"
        claimed = cast(
            CursorResult,
            await session.execute(
                update(DurableJob)
                .where(
                    DurableJob.id == job.id,
                    DurableJob.tenant_id == context.tenant_id,
                    DurableJob.status == previous_status,
                    DurableJob.attempts == previous_attempts,
                )
                .values(**values)
            ),
        )
        if claimed.rowcount == 1:
            break
        await session.rollback()
    else:
        return None
    if job is None:
        return None
    await session.refresh(job)
    await record_audit(
        session,
        replace(context, trace_id=job.trace_id) if job.trace_id else context,
        "job.claimed",
        "durable_job",
        job.id,
        details={"worker_id": worker_id, "attempt": job.attempts},
    )
    await session.commit()
    await session.refresh(job)
    return job
