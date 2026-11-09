from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import RequestContext
from ...config import settings
from ...models import Agent, AgentMessage, AgentRun
from ...schemas import AgentStepCreate, DelegationInput
from ..domain import FAILED_RUN_STATUSES, TERMINAL_RUN_STATUSES
from .base import _audit_run, _digest

__all__ = [
    "_ancestor_agent_ids", "_consecutive_failures", "_spawn_child",
]


async def _ancestor_agent_ids(session: AsyncSession, run: AgentRun) -> set[str]:
    chain = {run.agent_id}
    current = run
    while current.parent_run_id:
        parent = await session.scalar(
            select(AgentRun).where(
                AgentRun.id == current.parent_run_id, AgentRun.tenant_id == run.tenant_id
            )
        )
        if parent is None:
            break
        chain.add(parent.agent_id)
        current = parent
    return chain


async def _consecutive_failures(session: AsyncSession, run: AgentRun, agent_id: str) -> int:
    statuses = await session.scalars(
        select(AgentRun.status)
        .where(
            AgentRun.tenant_id == run.tenant_id,
            AgentRun.root_run_id == run.root_run_id,
            AgentRun.agent_id == agent_id,
            AgentRun.status.in_(TERMINAL_RUN_STATUSES),
        )
        .order_by(AgentRun.completed_at.desc(), AgentRun.id.desc())
        .limit(settings.agent_repeated_failure_threshold)
    )
    count = 0
    for status in statuses:
        if status not in FAILED_RUN_STATUSES:
            break
        count += 1
    return count


async def _spawn_child(
    session: AsyncSession,
    context: RequestContext,
    run: AgentRun,
    target: Agent,
    request: DelegationInput,
    payload: AgentStepCreate,
    raw: dict[str, Any],
    deadline: datetime,
    objective_hash: str,
) -> AgentRun:
    child_id = str(uuid4())
    child = AgentRun(
        id=child_id,
        tenant_id=run.tenant_id,
        idempotency_key=f"delegate:{run.id}:{payload.step_key}",
        request_hash=_digest(raw),
        agent_id=target.id,
        agent_key=target.key,
        agent_version=target.agent_version,
        parent_run_id=run.id,
        root_run_id=run.root_run_id,
        depth=run.depth + 1,
        max_depth=min(run.max_depth, target.max_depth),
        max_fanout=min(target.max_fanout, settings.agent_max_fanout_cap),
        owner_id=run.owner_id,
        objective=request.objective.strip(),
        objective_hash=objective_hash,
        expected_result=request.expected_result,
        deadline_at=deadline,
        work_item_id=run.work_item_id,
        token_budget=request.token_budget,
        step_budget=request.step_budget,
        side_effect_budget=request.side_effect_budget,
        status="running",
        trace_id=context.trace_id,
    )
    session.add(child)
    await session.flush()
    session.add(
        AgentMessage(
            tenant_id=run.tenant_id,
            root_run_id=run.root_run_id,
            from_run_id=run.id,
            to_run_id=child.id,
            kind="delegation",
            body={
                "reason": request.reason,
                "objective": child.objective,
                "expected_result": request.expected_result,
                "deadline_at": deadline.isoformat(),
                "token_budget": request.token_budget,
                "step_budget": request.step_budget,
                "side_effect_budget": request.side_effect_budget,
            },
        )
    )
    await _audit_run(
        session, context, child, "agent.run.started", parent_run_id=run.id, depth=child.depth
    )
    return child
