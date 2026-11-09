from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import RequestContext
from ...models import AgentMessage, AgentRun, AgentStep
from ...pagination import page_statement
from .base import get_run

__all__ = [
    "list_messages", "list_runs", "list_steps",
]


async def list_runs(
    session: AsyncSession,
    context: RequestContext,
    *,
    limit: int,
    offset: int,
    cursor: str | None,
    status: str | None = None,
    agent_id: str | None = None,
    root_run_id: str | None = None,
) -> list[AgentRun]:
    statement = select(AgentRun).where(AgentRun.tenant_id == context.tenant_id)
    if status:
        statement = statement.where(AgentRun.status == status)
    if agent_id:
        statement = statement.where(AgentRun.agent_id == agent_id)
    if root_run_id:
        statement = statement.where(AgentRun.root_run_id == root_run_id)
    return list(await session.scalars(page_statement(statement, AgentRun, limit, offset, cursor)))


async def list_steps(
    session: AsyncSession, context: RequestContext, run_id: str
) -> list[AgentStep]:
    run = await get_run(session, context, run_id)
    return list(
        await session.scalars(
            select(AgentStep)
            .where(AgentStep.tenant_id == context.tenant_id, AgentStep.run_id == run.id)
            .order_by(AgentStep.seq)
        )
    )


async def list_messages(
    session: AsyncSession, context: RequestContext, run_id: str
) -> list[AgentMessage]:
    run = await get_run(session, context, run_id)
    return list(
        await session.scalars(
            select(AgentMessage)
            .where(
                AgentMessage.tenant_id == context.tenant_id,
                AgentMessage.root_run_id == run.root_run_id,
                (AgentMessage.from_run_id == run.id) | (AgentMessage.to_run_id == run.id),
            )
            .order_by(AgentMessage.created_at, AgentMessage.id)
        )
    )
