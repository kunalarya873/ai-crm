from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.deps import RequestContext
from ..domain import InvalidRequestError
from ..integrations import TRANSIENT_PROVIDER_CODES, sync_connection
from ..knowledge.indexing import run_index_job
from ..models import (
    DurableJob,
    IntegrationConnection,
    IntegrationSyncRun,
    WebhookEvent,
    utc_now,
)
from ..permissions import Permission
from .domain import JOB_TYPES

JobHandler = Callable[[AsyncSession, RequestContext, DurableJob], Awaitable[dict[str, Any]]]


def _payload_str(job: DurableJob, key: str) -> str:
    value = job.payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise InvalidRequestError(f"Job payload requires string field: {key}")
    return value


class SyncFailedError(RuntimeError):
    """Transient provider failure; the job is retried with backoff."""


async def _run_sync(
    session: AsyncSession, context: RequestContext, connection_id: str, mode: str
) -> IntegrationSyncRun:
    run = await sync_connection(session, context, connection_id, mode)
    if run.status == "failed":
        code = run.failure_code or "sync_failed"
        message = f"Sync failed: {code}"
        if code in TRANSIENT_PROVIDER_CODES:
            raise SyncFailedError(message)
        raise InvalidRequestError(message)
    return run


async def _integration_sync(
    session: AsyncSession, context: RequestContext, job: DurableJob
) -> dict[str, Any]:
    mode = job.payload.get("mode", "incremental")
    run = await _run_sync(session, context, _payload_str(job, "connection_id"), str(mode))
    return {"sync_run_id": run.id, "status": run.status}


async def _integration_webhook(
    session: AsyncSession, context: RequestContext, job: DurableJob
) -> dict[str, Any]:
    event = await session.scalar(
        select(WebhookEvent)
        .join(IntegrationConnection, IntegrationConnection.id == WebhookEvent.connection_id)
        .where(
            WebhookEvent.id == _payload_str(job, "event_id"),
            IntegrationConnection.tenant_id == context.tenant_id,
        )
    )
    if event is None:
        raise InvalidRequestError("Webhook event not found")
    if event.status == "processed":
        return {"event_id": event.id, "status": "processed"}
    event_id, connection_id = event.id, event.connection_id
    final_attempt = job.attempts >= job.max_attempts
    try:
        run = await _run_sync(session, context, connection_id, "incremental")
    except Exception as error:
        await session.rollback()
        non_retryable = isinstance(error, InvalidRequestError)
        if non_retryable or final_attempt:
            failed = await session.get_one(WebhookEvent, event_id)
            failed.status = "failed"
            failed.failure_code = type(error).__name__[:100]
            failed.processed_at = utc_now()
            await session.commit()
        raise
    event = await session.get_one(WebhookEvent, event_id)
    event.status = "processed"
    event.processed_at = utc_now()
    event.failure_code = None
    await session.commit()
    return {"event_id": event_id, "status": "processed", "sync_run_id": run.id}


async def _knowledge_index(
    session: AsyncSession, context: RequestContext, job: DurableJob
) -> dict[str, Any]:
    index_job = await run_index_job(session, context, _payload_str(job, "index_job_id"))
    return {"index_job_id": index_job.id, "status": index_job.status}


# Explicit allowlist: job types without an entry fail visibly as `no_handler`.
# reminder.dispatch is deliberately absent until a real delivery channel exists, so reminders
# are never marked delivered without being sent.
HANDLERS: dict[str, tuple[JobHandler, frozenset[Permission]]] = {
    "integration.sync": (_integration_sync, frozenset({Permission.INTEGRATIONS_SYNC})),
    "integration.webhook": (_integration_webhook, frozenset({Permission.INTEGRATIONS_SYNC})),
    "knowledge.index": (_knowledge_index, frozenset({Permission.KNOWLEDGE_MANAGE})),
}

if not set(HANDLERS) <= JOB_TYPES:
    raise RuntimeError("HANDLERS contains job types outside JOB_TYPES")
