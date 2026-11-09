from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import RequestContext
from ...audit import record_audit, record_outbox_event
from ...domain import ConflictError
from ...models import DurableJob
from .read import get_job

__all__ = [
    "cancel_job", "retry_job",
]


async def retry_job(
    session: AsyncSession,
    context: RequestContext,
    job_id: str,
) -> DurableJob:
    job = await get_job(session, context, job_id)
    if job.status not in {"failed", "dead_letter", "cancelled"}:
        raise ConflictError("Only failed, dead-letter, or cancelled jobs can be retried")
    job.status = "queued"
    job.attempts = 0
    job.next_attempt_at = None
    job.error_code = None
    job.error_detail = None
    await record_audit(session, context, "job.retried", "durable_job", job.id)
    await record_outbox_event(
        session,
        context,
        "job.retried",
        "durable_job",
        job.id,
    )
    await session.commit()
    await session.refresh(job)
    return job


async def cancel_job(
    session: AsyncSession,
    context: RequestContext,
    job_id: str,
) -> DurableJob:
    job = await get_job(session, context, job_id)
    if job.status in {"succeeded", "cancelled"}:
        return job
    job.status = "cancelled"
    job.lease_owner = None
    job.lease_expires_at = None
    job.timeout_at = None
    await record_audit(session, context, "job.cancelled", "durable_job", job.id)
    await session.commit()
    await session.refresh(job)
    return job
