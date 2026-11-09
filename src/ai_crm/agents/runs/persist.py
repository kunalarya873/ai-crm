from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import RequestContext
from ...audit import record_audit
from ...domain import VersionConflictError
from ...models import AgentRun, AgentStep
from ...schemas import AgentStepCreate
from .base import _run_details, _update_run
from .escalate import _escalate
from .outcome import _Outcome
from .terminate import _terminate

__all__ = [
    "_persist_step",
]


async def _persist_step(
    session: AsyncSession,
    context: RequestContext,
    run: AgentRun,
    payload: AgentStepCreate,
    request_hash: str,
    outcome: _Outcome,
) -> AgentStep:
    step = AgentStep(
        tenant_id=run.tenant_id,
        run_id=run.id,
        seq=run.steps_used + 1,
        step_key=payload.step_key,
        request_hash=request_hash,
        step_type=payload.step_type,
        status=outcome.status,
        input=payload.input,
        output=outcome.output,
        action_proposal_id=outcome.action_proposal_id,
        child_run_id=outcome.child_run_id,
        context_assembly_id=outcome.context_assembly_id,
        tokens=payload.tokens if outcome.charge else 0,
        error_code=outcome.error_code,
    )
    session.add(step)
    try:
        await session.flush()
    except IntegrityError as error:
        await session.rollback()
        raise VersionConflictError("record_version_conflict") from error
    spent = payload.tokens if outcome.charge else 0
    counters = {
        "steps_used": run.steps_used + 1,
        "tokens_used": run.tokens_used + spent + outcome.token_reserve,
        "side_effects_used": run.side_effects_used + outcome.side_effects,
    }
    if outcome.escalation is not None:
        await _escalate(
            session, context, run, outcome.escalation, step=step, extra_values=counters
        )
    elif outcome.run_status is not None:
        await _terminate(
            session,
            context,
            run,
            outcome.run_status,
            outcome.terminal_reason or outcome.run_status,
            extra_values=counters,
        )
    else:
        await _update_run(session, run, **counters)
    succeeded = outcome.error_code is None
    await record_audit(
        session,
        context,
        "agent.step.recorded" if succeeded else "agent.step.denied",
        "agent_step",
        step.id,
        outcome="success" if succeeded else "denied",
        reason=outcome.error_code,
        details=_run_details(
            run,
            step_type=step.step_type,
            step_status=step.status,
            action_proposal_id=step.action_proposal_id,
            child_run_id=step.child_run_id,
        ),
    )
    return step
