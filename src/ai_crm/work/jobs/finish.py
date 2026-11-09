from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import RequestContext
from ...audit import record_audit
from ...config import settings
from ...models import DurableJob, ReminderDelivery, utc_now
from ...schemas import JobFailureRequest
from .common import _ensure_worker
from .read import get_job

__all__ = [
    "_mark_reminder_delivered", "_mark_reminder_failed", "complete_job", "fail_job",
]


async def complete_job(
    session: AsyncSession,
    context: RequestContext,
    job_id: str,
    worker_id: str,
    result: dict[str, object],
) -> DurableJob:
    job = await get_job(session, context, job_id)
    if job.status == "succeeded":
        return job
    _ensure_worker(job, worker_id)
    job.status = "succeeded"
    job.result = result
    job.completed_at = utc_now()
    job.lease_owner = None
    job.lease_expires_at = None
    job.timeout_at = None
    await _mark_reminder_delivered(session, job)
    await record_audit(
        session,
        context,
        "job.completed",
        "durable_job",
        job.id,
        details={"worker_id": worker_id},
    )
    await session.commit()
    await session.refresh(job)
    return job


async def fail_job(
    session: AsyncSession,
    context: RequestContext,
    job_id: str,
    worker_id: str,
    payload: JobFailureRequest,
) -> DurableJob:
    job = await get_job(session, context, job_id)
    _ensure_worker(job, worker_id)
    now = utc_now()
    job.error_code = payload.error_code
    job.error_detail = payload.error_detail
    job.lease_owner = None
    job.lease_expires_at = None
    job.timeout_at = None
    if payload.retryable and job.attempts < job.max_attempts:
        delay = min(
            job.backoff_seconds * (2 ** max(job.attempts - 1, 0)),
            settings.job_max_backoff_seconds,
        )
        job.status = "retryable"
        job.next_attempt_at = now + timedelta(seconds=delay)
    elif payload.retryable:
        job.status = "dead_letter"
        job.next_attempt_at = None
    else:
        job.status = "failed"
        job.next_attempt_at = None
    await _mark_reminder_failed(session, job)
    await record_audit(
        session,
        context,
        "job.failed",
        "durable_job",
        job.id,
        outcome="failed",
        reason=payload.error_code,
        details={"status": job.status, "attempt": job.attempts},
    )
    await session.commit()
    await session.refresh(job)
    return job


async def _mark_reminder_delivered(session: AsyncSession, job: DurableJob) -> None:
    if job.job_type != "reminder.dispatch":
        return
    reminder_id = job.payload.get("reminder_id")
    if not isinstance(reminder_id, str):
        return
    reminder = await session.get(ReminderDelivery, reminder_id)
    if reminder is None:
        return
    reminder.attempts = job.attempts
    reminder.delivered_at = utc_now()
    if reminder.status != "acknowledged":
        reminder.status = "delivered"


async def _mark_reminder_failed(session: AsyncSession, job: DurableJob) -> None:
    if job.job_type != "reminder.dispatch":
        return
    reminder_id = job.payload.get("reminder_id")
    if not isinstance(reminder_id, str):
        return
    reminder = await session.get(ReminderDelivery, reminder_id)
    if reminder is None:
        return
    reminder.attempts = job.attempts
    reminder.last_error = job.error_detail or job.error_code
    if job.status in {"dead_letter", "failed"}:
        reminder.status = "failed"
