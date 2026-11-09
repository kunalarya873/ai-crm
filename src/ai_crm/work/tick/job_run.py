import asyncio
from collections.abc import Awaitable, Callable
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ...config import settings
from ...domain import CapabilityDisabledError, ConflictError, DomainError, InvalidRequestError
from ...models import DurableJob, IntegrationConnection, WebhookEvent
from ...schemas import JobFailureRequest
from ..breaker import CircuitBreaker
from ..handlers import HANDLERS, SyncFailedError
from ..jobs import claim_next_job, complete_job, fail_job, heartbeat_job
from .context import (
    CONNECTOR_JOB_TYPES,
    CONTROL,
    LEASE_GRACE_SECONDS,
    QUEUE,
    WORKER_ID,
    make_context,
)


async def job_provider(session: AsyncSession, tenant_id: str, job: DurableJob) -> str:
    statement = select(IntegrationConnection.provider_key).where(
        IntegrationConnection.tenant_id == tenant_id
    )
    if job.payload.get("connection_id") is not None:
        statement = statement.where(IntegrationConnection.id == str(job.payload["connection_id"]))
    elif job.payload.get("event_id") is not None:
        statement = statement.join(
            WebhookEvent, WebhookEvent.connection_id == IntegrationConnection.id
        ).where(WebhookEvent.id == str(job.payload["event_id"]))
    else:
        return "unknown"
    return await session.scalar(statement) or "unknown"


async def run_one(
    factory: async_sessionmaker[AsyncSession],
    tenant_id: str,
    *,
    breaker: CircuitBreaker,
    disabled_flags: Callable[[AsyncSession, str], Awaitable[frozenset[str]]],
) -> bool:
    """Claim and execute one job for a tenant; return False when nothing was ready."""
    async with factory() as session:
        claim_context = make_context(tenant_id, CONTROL)
        job_types = set(HANDLERS)
        if "connectors" in await disabled_flags(session, tenant_id):
            # Left queued, not failed, so the work resumes when the switch is turned back on.
            job_types -= CONNECTOR_JOB_TYPES
        if breaker.blocked():
            job_types -= CONNECTOR_JOB_TYPES
        job = await claim_next_job(
            session,
            claim_context,
            queue=QUEUE,
            worker_id=WORKER_ID,
            lease_seconds=settings.job_default_lease_seconds,
            # Types without a handler stay queued for external workers.
            job_types=job_types,
        )
        if job is None:
            return False
        job_id, job_type, timeout_seconds = job.id, job.job_type, job.timeout_seconds
        provider = None
        if job_type in CONNECTOR_JOB_TYPES:
            provider = await job_provider(session, tenant_id, job)
            breaker.start_probe(provider)
        trace_id = job.trace_id or uuid4().hex
        claim_context = make_context(tenant_id, CONTROL, trace_id)
        await heartbeat_job(
            session, claim_context, job_id, WORKER_ID, timeout_seconds + LEASE_GRACE_SECONDS
        )
        entry = HANDLERS.get(job_type)
        if entry is None:
            await fail_job(
                session,
                claim_context,
                job_id,
                WORKER_ID,
                JobFailureRequest(
                    error_code="no_handler",
                    error_detail=f"No handler for job type {job_type}",
                    retryable=False,
                ),
            )
            return True
        handler, permissions = entry
        timeout_scope = asyncio.timeout(timeout_seconds)
        try:
            # The handler gets its own session so a timeout cancelling it mid-query cannot
            # leave the claim session (used for complete/fail) in an unknown state.
            async with timeout_scope, factory() as handler_session:
                result = await handler(
                    handler_session, make_context(tenant_id, permissions, trace_id), job
                )
        except Exception as error:
            timed_out = isinstance(error, TimeoutError) and timeout_scope.expired()
            if provider is not None:
                if isinstance(error, SyncFailedError) or timed_out:
                    breaker.record_failure(provider)
                else:
                    breaker.release(provider)
            code = "job_timeout" if timed_out else type(error).__name__
            retryable = isinstance(error, CapabilityDisabledError) or not (
                isinstance(error, InvalidRequestError)
                or (isinstance(error, DomainError) and not isinstance(error, ConflictError))
            )
            await fail_job(
                session,
                claim_context,
                job_id,
                WORKER_ID,
                JobFailureRequest(
                    error_code=code[:100], error_detail=str(error)[:500], retryable=retryable
                ),
            )
            return True
        if provider is not None:
            breaker.record_success(provider)
        await complete_job(session, claim_context, job_id, WORKER_ID, result)
        return True
