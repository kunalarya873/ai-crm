from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import (
    AgentRun,
    IntegrationConnection,
    IntegrationSyncRun,
    KnowledgeSource,
)
from ..service import _as_utc

__all__ = [
    "_overdue_agent_runs", "_search_freshness", "_sync_freshness",
]


async def _sync_freshness(
    session: AsyncSession, tenant_id: str, now: datetime
) -> tuple[float | None, dict]:
    connections = (
        await session.execute(
            select(IntegrationConnection.id, IntegrationConnection.created_at).where(
                IntegrationConnection.tenant_id == tenant_id,
                IntegrationConnection.status == "connected",
            )
        )
    ).all()
    if not connections:
        return None, {"connected_connections": 0}
    last_success = dict(
        (
            await session.execute(
                select(
                    IntegrationSyncRun.connection_id, func.max(IntegrationSyncRun.last_success_at)
                )
                .where(IntegrationSyncRun.connection_id.in_([c.id for c in connections]))
                .group_by(IntegrationSyncRun.connection_id)
            )
        ).all()
    )
    ages: dict[str, float] = {}
    for connection_id, created_at in connections:
        reference = _as_utc(last_success.get(connection_id)) or _as_utc(created_at)
        assert reference is not None
        ages[connection_id] = (now - reference).total_seconds()
    worst = max(ages, key=lambda key: ages[key])
    return ages[worst], {"connected_connections": len(connections), "worst_connection_id": worst}


async def _search_freshness(
    session: AsyncSession, tenant_id: str, now: datetime
) -> tuple[float | None, dict]:
    base = (
        KnowledgeSource.tenant_id == tenant_id,
        KnowledgeSource.status == "active",
        KnowledgeSource.searchable.is_(True),
        KnowledgeSource.fresh_until.is_not(None),
    )
    total = await session.scalar(select(func.count()).select_from(KnowledgeSource).where(*base))
    if not total:
        return None, {"sources_with_freshness": 0}
    stale = await session.scalar(
        select(func.count())
        .select_from(KnowledgeSource)
        .where(*base, KnowledgeSource.fresh_until < now)
    )
    return (stale or 0) / total, {"sources_with_freshness": total, "stale_sources": stale or 0}


async def _overdue_agent_runs(session: AsyncSession, tenant_id: str, now: datetime) -> float:
    count = await session.scalar(
        select(func.count())
        .select_from(AgentRun)
        .where(
            AgentRun.tenant_id == tenant_id,
            AgentRun.status.in_({"running", "paused", "waiting_human"}),
            AgentRun.deadline_at < now,
        )
    )
    return float(count or 0)
