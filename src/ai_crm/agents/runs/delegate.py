from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import RequestContext
from ...config import settings
from ...domain import InvalidRequestError, NotFoundError, normalize_name
from ...models import Agent, AgentRun, utc_now
from ...schemas import AgentStepCreate, DelegationInput
from ..domain import ACTIVE_RUN_STATUSES
from .base import _aware, _digest
from .delegate_helpers import _ancestor_agent_ids, _consecutive_failures, _spawn_child
from .escalate import _Escalation
from .outcome import _denial, _Outcome, _parse, _reject

__all__ = [
    "_do_delegate",
]


async def _do_delegate(
    session: AsyncSession,
    context: RequestContext,
    run: AgentRun,
    agent: Agent,
    raw: dict[str, Any],
    payload: AgentStepCreate,
) -> _Outcome:
    if "delegate" not in agent.allowed_capabilities:
        return _denial("capability_missing", "The agent is not allowed to delegate.")
    request = _parse(DelegationInput, raw, "delegate")
    target = await session.scalar(
        select(Agent).where(Agent.tenant_id == run.tenant_id, Agent.key == request.agent_key)
    )
    if target is None:
        raise NotFoundError("Target agent not found")
    if target.status != "active":
        return _reject("target_agent_inactive", f"Target agent is {target.status}")
    if target.id in await _ancestor_agent_ids(session, run):
        return _reject("delegation_cycle", "Delegation would revisit an agent already in the chain")
    if run.depth + 1 > run.max_depth:
        return _reject("max_depth_exceeded", f"Delegation depth is limited to {run.max_depth}")
    fanout = await session.scalar(
        select(func.count())
        .select_from(AgentRun)
        .where(AgentRun.tenant_id == run.tenant_id, AgentRun.parent_run_id == run.id)
    )
    if (fanout or 0) >= run.max_fanout:
        return _reject("max_fanout_exceeded", f"Fan-out is limited to {run.max_fanout}")
    objective_hash = _digest(normalize_name(request.objective))
    duplicate = await session.scalar(
        select(AgentRun.id).where(
            AgentRun.tenant_id == run.tenant_id,
            AgentRun.root_run_id == run.root_run_id,
            AgentRun.objective_hash == objective_hash,
            AgentRun.status.in_(ACTIVE_RUN_STATUSES),
        )
    )
    if duplicate is not None:
        return _reject("duplicate_ownership", "Another active run already owns this objective")
    if request.deadline_at.tzinfo is None:
        raise InvalidRequestError("deadline_at must include a timezone")
    deadline = _aware(request.deadline_at)
    if deadline <= utc_now() or deadline > _aware(run.deadline_at):
        return _reject(
            "invalid_deadline", "Child deadline must be in the future and within the parent's"
        )
    if (
        request.token_budget > target.token_budget
        or request.step_budget > target.step_budget
        or request.side_effect_budget > target.side_effect_budget
    ):
        return _reject("exceeds_target_agent_limits", "Budget exceeds the target agent's limits")
    if request.token_budget > run.token_budget - run.tokens_used - payload.tokens:
        return _reject("insufficient_token_budget", "Parent has too few tokens left to carve out")
    if request.side_effect_budget > run.side_effect_budget - run.side_effects_used:
        return _reject(
            "insufficient_side_effect_budget", "Parent has too few side effects left to carve out"
        )
    if (
        await _consecutive_failures(session, run, target.id)
        >= settings.agent_repeated_failure_threshold
    ):
        return _Outcome(
            status="escalated",
            error_code="repeated_failure",
            output={"detail": "Target agent keeps failing under this root run."},
            escalation=_Escalation(
                reason="repeated_failure",
                summary=f"Agent {target.key} failed repeatedly on delegated work.",
                evidence=[{"agent_key": target.key}],
                next_steps=["Investigate the agent or take over the objective manually."],
            ),
        )
    child = await _spawn_child(
        session, context, run, target, request, payload, raw, deadline, objective_hash
    )
    return _Outcome(
        child_run_id=child.id,
        token_reserve=request.token_budget,
        side_effects=request.side_effect_budget,
        output={"child_run_id": child.id, "agent_key": target.key, "depth": child.depth},
    )
