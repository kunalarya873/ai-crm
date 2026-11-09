from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.deps import RequestContext
from ..audit import record_audit, record_outbox_event
from ..config import settings
from ..domain import ConflictError, InvalidRequestError
from ..flags import require_capability
from ..models import IntegrationSyncRun, utc_now
from .connections import get_connection
from .contract import SYNC_RETRY_BASE_SECONDS, TRANSIENT_PROVIDER_CODES, ConnectorProviderError
from .fixture import connection_is_writable, get_connector
from .upsert import _upsert_activity_record

__all__ = [
    "sync_connection",
]


async def sync_connection(
    session: AsyncSession,
    context: RequestContext,
    connection_id: str,
    mode: str,
) -> IntegrationSyncRun:
    await require_capability(session, context, "connectors", operation="connector.sync")
    connection = await get_connection(session, context, connection_id)
    connection_is_writable(connection)
    if mode not in {"initial", "incremental", "reconcile"}:
        raise InvalidRequestError("Unsupported sync mode")
    active_run = await session.scalar(
        select(IntegrationSyncRun).where(
            IntegrationSyncRun.connection_id == connection_id,
            IntegrationSyncRun.status == "running",
            IntegrationSyncRun.lease_expires_at > utc_now(),
        )
    )
    if active_run is not None:
        raise ConflictError("A sync is already running for this connection")
    previous_cursor = None
    if mode != "initial":
        previous_cursor = await session.scalar(
            select(IntegrationSyncRun.cursor)
            .where(
                IntegrationSyncRun.connection_id == connection_id,
                IntegrationSyncRun.status == "succeeded",
            )
            .order_by(IntegrationSyncRun.created_at.desc())
            .limit(1)
        )

    previous_run = (
        await session.execute(
            select(IntegrationSyncRun.status, IntegrationSyncRun.retry_count)
            .where(IntegrationSyncRun.connection_id == connection_id)
            .order_by(IntegrationSyncRun.created_at.desc())
            .limit(1)
        )
    ).first()
    consecutive_failures = (
        previous_run.retry_count if previous_run and previous_run.status == "failed" else 0
    )

    run = IntegrationSyncRun(
        connection_id=connection.id,
        resource_type="activities",
        mode=mode,
        status="running",
        cursor=previous_cursor,
        lease_owner=context.actor_id,
        lease_expires_at=utc_now() + timedelta(seconds=settings.integration_lease_seconds),
        started_at=utc_now(),
        last_attempt_at=utc_now(),
    )
    session.add(run)
    await session.flush()
    connector = get_connector(connection.provider_key)
    try:
        page = await connector.list_activities(connection, run.cursor)
        for record in page.records:
            await _upsert_activity_record(session, connection, record)
        run.cursor = page.next_cursor
        run.records_processed = len(page.records)
        run.status = "succeeded"
        run.last_success_at = utc_now()
        run.finished_at = utc_now()
        run.lease_owner = None
        run.lease_expires_at = None
        await record_audit(
            session,
            context,
            "integration.sync.succeeded",
            "integration_sync_run",
            run.id,
            details={"records_processed": run.records_processed},
        )
        await record_outbox_event(
            session,
            context,
            "integration.sync.succeeded",
            "integration_sync_run",
            run.id,
            {"records_processed": run.records_processed, "cursor": run.cursor},
        )
    except ConnectorProviderError as error:
        run.status = "failed"
        run.failure_code = error.code
        run.failure_detail = str(error)
        run.retry_count = consecutive_failures + 1
        # Permanent failures are not retried automatically; an operator must intervene.
        run.next_retry_at = (
            utc_now()
            + timedelta(
                seconds=min(
                    SYNC_RETRY_BASE_SECONDS * 2 ** (run.retry_count - 1),
                    settings.job_max_backoff_seconds,
                )
            )
            if error.code in TRANSIENT_PROVIDER_CODES
            else None
        )
        run.finished_at = utc_now()
        run.lease_owner = None
        run.lease_expires_at = None
    await session.commit()
    await session.refresh(run)
    return run
