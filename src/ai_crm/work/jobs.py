import hashlib
import json
from collections.abc import Collection
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import cast

from sqlalchemy import func, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.deps import RequestContext
from ..audit import record_audit, record_outbox_event
from ..config import settings
from ..domain import BackpressureError, ConflictError, InvalidRequestError, NotFoundError
from ..models import DurableJob, ReminderDelivery, utc_now
from ..schemas import JobCreate, JobFailureRequest
from .domain import JOB_TYPES


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _hash_request(
    *,
    job_type: str,
    queue: str,
    priority: int,
    payload: dict[str, object],
    run_at: datetime,
    max_attempts: int,
    backoff_seconds: int,
    timeout_seconds: int,
) -> str:
    value = {
        "job_type": job_type,
        "queue": queue,
        "priority": priority,
        "payload": payload,
        "run_at": run_at.isoformat(),
        "max_attempts": max_attempts,
        "backoff_seconds": backoff_seconds,
        "timeout_seconds": timeout_seconds,
    }
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode()).hexdigest()


def _validate_job_request(job_type: str, run_at: datetime) -> None:
    if job_type not in JOB_TYPES:
        raise InvalidRequestError(f"Unsupported job type: {job_type}")
    if run_at.tzinfo is None:
        raise InvalidRequestError("run_at must include a timezone")


async def get_job(
    session: AsyncSession,
    context: RequestContext,
    job_id: str,
) -> DurableJob:
    job = await session.scalar(
        select(DurableJob).where(
            DurableJob.id == job_id,
            DurableJob.tenant_id == context.tenant_id,
        )
    )
    if job is None:
        raise NotFoundError("Job not found")
    return job


async def create_job_in_session(
    session: AsyncSession,
    context: RequestContext,
    *,
    idempotency_key: str,
    job_type: str,
    queue: str,
    payload: dict[str, object],
    run_at: datetime | None = None,
    priority: int = 50,
    max_attempts: int = 3,
    backoff_seconds: int = 30,
    timeout_seconds: int = 300,
    request_hash_override: str | None = None,
) -> DurableJob:
    if not idempotency_key.strip():
        raise InvalidRequestError("Idempotency-Key header is required")
    scheduled_for = run_at or utc_now()
    _validate_job_request(job_type, scheduled_for)
    request_hash = request_hash_override or _hash_request(
        job_type=job_type,
        queue=queue,
        priority=priority,
        payload=payload,
        run_at=scheduled_for,
        max_attempts=max_attempts,
        backoff_seconds=backoff_seconds,
        timeout_seconds=timeout_seconds,
    )
    existing = await session.scalar(
        select(DurableJob).where(
            DurableJob.tenant_id == context.tenant_id,
            DurableJob.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_hash != request_hash:
            raise ConflictError("Idempotency-Key was reused with a different job")
        return existing
    job = DurableJob(
        tenant_id=context.tenant_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        job_type=job_type,
        queue=queue,
        trace_id=context.trace_id,
        priority=priority,
        payload=payload,
        run_at=scheduled_for,
        max_attempts=max_attempts,
        backoff_seconds=backoff_seconds,
        timeout_seconds=timeout_seconds,
    )
    session.add(job)
    await session.flush()
    return job


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


async def list_jobs(
    session: AsyncSession,
    context: RequestContext,
    *,
    limit: int,
    offset: int,
    queue: str | None = None,
    job_status: str | None = None,
) -> list[DurableJob]:
    statement = select(DurableJob).where(DurableJob.tenant_id == context.tenant_id)
    if queue:
        statement = statement.where(DurableJob.queue == queue)
    if job_status:
        statement = statement.where(DurableJob.status == job_status)
    result = await session.scalars(
        statement.order_by(DurableJob.created_at.desc()).offset(offset).limit(limit)
    )
    return list(result)


CLAIM_ATTEMPTS = 3


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
    ready = (
        (
            DurableJob.status.in_({"queued", "retryable"})
            & (DurableJob.run_at <= now)
            & or_(DurableJob.next_attempt_at.is_(None), DurableJob.next_attempt_at <= now)
        )
        | (
            (DurableJob.status == "running")
            & (DurableJob.lease_expires_at <= now)
        )
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


async def reconcile_expired_jobs(
    session: AsyncSession,
    context: RequestContext,
) -> list[DurableJob]:
    now = utc_now()
    result = await session.scalars(
        select(DurableJob).where(
            DurableJob.tenant_id == context.tenant_id,
            DurableJob.status == "running",
            or_(DurableJob.lease_expires_at <= now, DurableJob.timeout_at <= now),
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


def _ensure_worker(job: DurableJob, worker_id: str) -> None:
    if job.status != "running":
        raise ConflictError(f"Job is not running: {job.status}")
    if job.lease_owner != worker_id:
        raise ConflictError("Job is leased by another worker")
    lease_expires_at = _aware(job.lease_expires_at)
    if lease_expires_at is not None and lease_expires_at <= utc_now():
        raise ConflictError("Job lease has expired")


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
