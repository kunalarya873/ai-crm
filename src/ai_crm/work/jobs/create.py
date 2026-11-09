from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import RequestContext
from ...domain import ConflictError, InvalidRequestError
from ...models import DurableJob, utc_now
from .common import _hash_request, _validate_job_request

__all__ = [
    "create_job_in_session",
]


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
