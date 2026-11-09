from datetime import timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import RequestContext
from ...config import settings
from ...domain import ConflictError, InvalidRequestError, NotFoundError, normalize_name
from ...flags import require_capability
from ...models import Agent, AgentRun, WorkItem, utc_now
from ...schemas import AgentRunCreate
from .base import _audit_run, _aware, _digest, _get_agent

__all__ = [
    "_resolve_budgets", "start_run",
]


def _resolve_budgets(agent: Agent, payload: AgentRunCreate) -> dict[str, int]:
    budgets = {
        "token_budget": payload.token_budget or agent.token_budget,
        "step_budget": payload.step_budget or agent.step_budget,
        "side_effect_budget": (
            agent.side_effect_budget
            if payload.side_effect_budget is None
            else payload.side_effect_budget
        ),
    }
    caps = {
        "token_budget": settings.agent_token_budget_cap,
        "step_budget": settings.agent_step_budget_cap,
        "side_effect_budget": settings.agent_side_effect_budget_cap,
    }
    for name, value in budgets.items():
        if value > getattr(agent, name):
            raise InvalidRequestError(f"{name} exceeds the agent's registered limit")
        if value > caps[name]:
            raise InvalidRequestError(f"{name} exceeds the platform cap of {caps[name]}")
    return budgets


async def start_run(
    session: AsyncSession,
    context: RequestContext,
    payload: AgentRunCreate,
    idempotency_key: str,
) -> AgentRun:
    if not idempotency_key.strip():
        raise InvalidRequestError("Idempotency-Key header is required")
    await require_capability(session, context, "agents", operation="agent.run.start")
    if idempotency_key.startswith("delegate:"):
        raise InvalidRequestError("Idempotency-Key prefix 'delegate:' is reserved")
    request_hash = _digest(payload.model_dump(mode="json"))
    existing = await session.scalar(
        select(AgentRun).where(
            AgentRun.tenant_id == context.tenant_id,
            AgentRun.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.owner_id != context.actor_id:
            raise ConflictError("Idempotency-Key was reused for a different agent run")
        if existing.request_hash != request_hash:
            raise ConflictError("Idempotency-Key was reused for a different agent run")
        return existing
    agent = await _get_agent(session, context.tenant_id, payload.agent_id)
    if agent is None:
        raise NotFoundError("Agent not found")
    if agent.status != "active":
        raise ConflictError(f"Agent is {agent.status} and cannot start runs")
    if payload.deadline_at.tzinfo is None:
        raise InvalidRequestError("deadline_at must include a timezone")
    now = utc_now()
    deadline = _aware(payload.deadline_at)
    if deadline <= now:
        raise InvalidRequestError("deadline_at must be in the future")
    if deadline > now + timedelta(hours=settings.agent_max_run_hours):
        raise InvalidRequestError(
            f"deadline_at is more than {settings.agent_max_run_hours} hours away"
        )
    budgets = _resolve_budgets(agent, payload)
    if payload.work_item_id is not None:
        found = await session.scalar(
            select(WorkItem.id).where(
                WorkItem.id == payload.work_item_id, WorkItem.tenant_id == context.tenant_id
            )
        )
        if found is None:
            raise InvalidRequestError("Unknown work_item_id")
    run_id = str(uuid4())
    run = AgentRun(
        id=run_id,
        tenant_id=context.tenant_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        agent_id=agent.id,
        agent_key=agent.key,
        agent_version=agent.agent_version,
        root_run_id=run_id,
        depth=0,
        max_depth=min(agent.max_depth, settings.agent_max_depth_cap),
        max_fanout=min(agent.max_fanout, settings.agent_max_fanout_cap),
        owner_id=context.actor_id,
        objective=payload.objective,
        objective_hash=_digest(normalize_name(payload.objective)),
        expected_result=payload.expected_result,
        deadline_at=deadline,
        work_item_id=payload.work_item_id,
        status="running",
        trace_id=context.trace_id,
        **budgets,
    )
    session.add(run)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        winner = await session.scalar(
            select(AgentRun).where(
                AgentRun.tenant_id == context.tenant_id,
                AgentRun.idempotency_key == idempotency_key,
            )
        )
        if (
            winner is None
            or winner.request_hash != request_hash
            or winner.owner_id != context.actor_id
        ):
            raise ConflictError("Idempotency-Key was reused for a different agent run") from None
        return winner
    await _audit_run(session, context, run, "agent.run.started", work_item_id=run.work_item_id)
    await session.commit()
    await session.refresh(run)
    return run
