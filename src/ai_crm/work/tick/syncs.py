import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ...config import settings
from ...domain import BackpressureError
from ...flags import is_enabled
from ...integrations import TRANSIENT_PROVIDER_CODES, ConnectorProviderError, refresh_connection
from ...models import IntegrationConnection, IntegrationSyncRun
from ...permissions import Permission
from ...schemas import JobCreate
from .context import CONTROL, aware, make_context

logger = logging.getLogger("ai_crm.work.runner")


async def schedule_syncs(
    factory: async_sessionmaker[AsyncSession],
    tenant_id: str,
    now: datetime,
    *,
    create_job: Callable[..., Awaitable[Any]],
) -> int:
    """Enqueue one incremental sync per healthy connection for the current interval bucket."""
    bucket = int(now.timestamp()) // settings.integration_sync_interval_seconds
    async with factory() as session:
        if not await is_enabled(session, tenant_id, "connectors"):
            return 0
        connections = list(
            await session.execute(
                select(IntegrationConnection.id, IntegrationConnection.token_expires_at).where(
                    IntegrationConnection.tenant_id == tenant_id,
                    IntegrationConnection.status == "connected",
                )
            )
        )
        refresh_context = make_context(tenant_id, frozenset({Permission.INTEGRATIONS_MANAGE}))
        enqueued = 0
        for connection_id, expires_at in connections:
            try:
                latest = (
                    await session.execute(
                        select(
                            IntegrationSyncRun.status,
                            IntegrationSyncRun.next_retry_at,
                            IntegrationSyncRun.failure_code,
                        )
                        .where(IntegrationSyncRun.connection_id == connection_id)
                        .order_by(IntegrationSyncRun.created_at.desc())
                        .limit(1)
                    )
                ).first()
                if latest is not None and latest.status == "failed":
                    permanent = latest.failure_code not in TRANSIENT_PROVIDER_CODES
                    backing_off = (
                        latest.next_retry_at is not None and aware(latest.next_retry_at) > now
                    )
                    if permanent or backing_off:
                        continue
                if expires_at is not None and aware(expires_at) <= now:
                    # Permanent refresh failures flip the connection to needs_reauth, which
                    # the proactive checks turn into an alert; transient ones retry next interval.
                    try:
                        await refresh_connection(session, refresh_context, connection_id)
                    except ConnectorProviderError:
                        continue
                await create_job(
                    session,
                    make_context(tenant_id, CONTROL, uuid4().hex),
                    JobCreate(
                        job_type="integration.sync",
                        payload={"connection_id": connection_id, "mode": "incremental"},
                    ),
                    f"sync:{connection_id}:{bucket}",
                )
                enqueued += 1
            except BackpressureError:
                await session.rollback()
                logger.warning("job backlog full for tenant %s; sync scheduling skipped", tenant_id)
                break
            except Exception:
                await session.rollback()
                logger.exception("could not schedule sync for connection %s", connection_id)
    return enqueued
