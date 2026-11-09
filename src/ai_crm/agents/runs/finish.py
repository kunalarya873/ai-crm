from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import RequestContext
from ...models import Agent, AgentRun
from ...schemas import AgentStepCreate, EscalationInput, OutputInput
from ..domain import ACTIVE_RUN_STATUSES
from .escalate import _Escalation
from .outcome import _denial, _Outcome, _parse, _reject

__all__ = [
    "_do_escalate", "_do_output",
]


async def _do_escalate(
    session: AsyncSession,
    context: RequestContext,
    run: AgentRun,
    agent: Agent,
    raw: dict[str, Any],
    payload: AgentStepCreate,
) -> _Outcome:
    request = _parse(EscalationInput, raw, "escalate")
    if "escalate" not in agent.allowed_capabilities:
        return _denial("capability_missing", "The agent is not allowed to escalate on its own.")
    return _Outcome(
        status="escalated",
        output={"reason": request.reason},
        escalation=_Escalation(
            reason=request.reason,
            summary=request.summary,
            evidence=request.evidence_refs,
            next_steps=request.proposed_next_steps,
        ),
    )


async def _do_output(
    session: AsyncSession,
    context: RequestContext,
    run: AgentRun,
    agent: Agent,
    raw: dict[str, Any],
    payload: AgentStepCreate,
) -> _Outcome:
    request = _parse(OutputInput, raw, "output")
    if request.outcome == "success":
        open_children = await session.scalar(
            select(func.count())
            .select_from(AgentRun)
            .where(
                AgentRun.tenant_id == run.tenant_id,
                AgentRun.parent_run_id == run.id,
                AgentRun.status.in_(ACTIVE_RUN_STATUSES),
            )
        )
        if open_children:
            return _reject("children_active", "Delegated runs are still active")
    failed = request.outcome == "failed"
    return _Outcome(
        output={"outcome": request.outcome, "summary": request.summary, "result": request.result},
        run_status="failed" if failed else "completed",
        terminal_reason="agent_reported_failure" if failed else "completed",
    )
