from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .api.deps import RequestContext
from .flags import effective_flags
from .models import (
    ActionExecution,
    ActionProposal,
    AgentRun,
    AIRun,
    DurableJob,
    IntegrationConnection,
    Membership,
    OperationalAlert,
)
from .schemas import AdminUsageRead


async def _counts(session: AsyncSession, statement: Select) -> dict[str, int]:
    return {str(key): int(count) for key, count in (await session.execute(statement)).all()}


async def tenant_usage(session: AsyncSession, context: RequestContext) -> AdminUsageRead:
    tenant_id = context.tenant_id

    def by(column, model):  # noqa: ANN001, ANN202
        return select(column, func.count()).where(model.tenant_id == tenant_id).group_by(column)

    ai = (
        await session.execute(
            select(
                func.count(),
                func.coalesce(func.sum(AIRun.estimated_cost_micros), 0),
                func.coalesce(func.sum(AIRun.total_tokens), 0),
            ).where(AIRun.tenant_id == tenant_id)
        )
    ).one()
    fallbacks = await session.scalar(
        select(func.count()).where(AIRun.tenant_id == tenant_id, AIRun.status == "fallback")
    )
    open_alerts = await session.scalar(
        select(func.count()).where(
            OperationalAlert.tenant_id == tenant_id,
            OperationalAlert.status.in_({"open", "acknowledged"}),
        )
    )
    return AdminUsageRead(
        members_by_role=await _counts(
            session,
            select(Membership.role, func.count())
            .where(Membership.tenant_id == tenant_id, Membership.is_active.is_(True))
            .group_by(Membership.role),
        ),
        connections_by_status=await _counts(
            session, by(IntegrationConnection.status, IntegrationConnection)
        ),
        jobs_by_status=await _counts(session, by(DurableJob.status, DurableJob)),
        ai_runs={
            "runs": int(ai[0]),
            "fallbacks": int(fallbacks or 0),
            "estimated_cost_micros": int(ai[1]),
            "total_tokens": int(ai[2]),
        },
        action_proposals_by_status=await _counts(
            session, by(ActionProposal.status, ActionProposal)
        ),
        action_executions_by_status=await _counts(
            session, by(ActionExecution.status, ActionExecution)
        ),
        agent_runs_by_status=await _counts(session, by(AgentRun.status, AgentRun)),
        open_alerts=int(open_alerts or 0),
        capabilities=await effective_flags(session, tenant_id),
    )
