from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.deps import RequestContext
from ..models import IntegrationRecordLink, IntegrationSyncRun
from .connections import get_connection

__all__ = [
    "list_record_links", "list_sync_runs",
]


async def list_sync_runs(
    session: AsyncSession,
    context: RequestContext,
    connection_id: str,
) -> list[IntegrationSyncRun]:
    await get_connection(session, context, connection_id)
    result = await session.scalars(
        select(IntegrationSyncRun)
        .where(IntegrationSyncRun.connection_id == connection_id)
        .order_by(IntegrationSyncRun.created_at.desc())
    )
    return list(result)


async def list_record_links(
    session: AsyncSession,
    context: RequestContext,
    connection_id: str,
) -> list[IntegrationRecordLink]:
    await get_connection(session, context, connection_id)
    result = await session.scalars(
        select(IntegrationRecordLink)
        .where(IntegrationRecordLink.connection_id == connection_id)
        .order_by(IntegrationRecordLink.last_seen_at.desc())
    )
    return list(result)
