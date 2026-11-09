from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import RequestContext
from ...domain import ConflictError, InvalidTransitionError
from ...flags import require_capability
from ...models import Agent, AgentRun, AgentStep, utc_now
from ...schemas import AgentRunRead, AgentStepCreate, AgentStepRead, AgentStepResult
from .base import _authorize, _aware, _digest, _get_agent, get_run
from .delegate import _do_delegate
from .escalate import _escalate, _Escalation
from .finish import _do_escalate, _do_output
from .outcome import _budget_exhausted, _Outcome
from .persist import _persist_step
from .propose import _do_propose
from .retrieve import _do_retrieve

__all__ = [
    "_HANDLERS", "_Handler", "submit_step",
]


_Handler = Callable[
    [AsyncSession, RequestContext, AgentRun, Agent, dict[str, Any], AgentStepCreate],
    Awaitable[_Outcome],
]


_HANDLERS: dict[str, _Handler] = {
    "retrieve": _do_retrieve,
    "propose": _do_propose,
    "delegate": _do_delegate,
    "escalate": _do_escalate,
    "output": _do_output,
}


async def submit_step(
    session: AsyncSession,
    context: RequestContext,
    run_id: str,
    payload: AgentStepCreate,
) -> AgentStepResult:
    run = await get_run(session, context, run_id)
    _authorize(context, run, allow_manage=False)
    request_hash = _digest(payload.step_type, payload.input, payload.tokens)
    existing = await session.scalar(
        select(AgentStep).where(
            AgentStep.run_id == run.id,
            AgentStep.tenant_id == run.tenant_id,
            AgentStep.step_key == payload.step_key,
        )
    )
    if existing is not None:
        if existing.request_hash != request_hash:
            raise ConflictError("step_key was reused for a different step")
        if existing.status == "rejected":
            raise ConflictError(str(existing.output.get("detail", "Step was rejected")))
        return AgentStepResult(
            step=AgentStepRead.model_validate(existing), run=AgentRunRead.model_validate(run)
        )
    await require_capability(session, context, "agents", operation="agent.step")
    if run.status != "running":
        raise InvalidTransitionError(f"Agent run is {run.status}; steps need a running run")
    agent = await _get_agent(session, run.tenant_id, run.agent_id)
    if agent is None or agent.status != "active":
        raise ConflictError("Agent is not active")
    if _aware(run.deadline_at) <= utc_now():
        await _escalate(
            session,
            context,
            run,
            _Escalation(
                reason="deadline_exceeded",
                summary="The run passed its deadline before reaching a terminal state.",
                run_status="failed",
            ),
        )
        await session.commit()
        raise ConflictError("Agent run deadline has passed")

    if run.steps_used >= run.step_budget:
        outcome = _budget_exhausted("step")
    elif run.tokens_used + payload.tokens > run.token_budget:
        outcome = _budget_exhausted("token")
    else:
        outcome = await _HANDLERS[payload.step_type](
            session, context, run, agent, payload.input, payload
        )

    step = await _persist_step(session, context, run, payload, request_hash, outcome)
    if outcome.reject is not None:
        await session.commit()
        raise ConflictError(outcome.reject)
    await session.commit()
    await session.refresh(run)
    await session.refresh(step)
    return AgentStepResult(
        step=AgentStepRead.model_validate(step), run=AgentRunRead.model_validate(run)
    )
