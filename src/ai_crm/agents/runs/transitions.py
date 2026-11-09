from datetime import datetime

from sqlalchemy import ColumnElement, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import RequestContext
from ...domain import (
    ConflictError,
    InvalidRequestError,
    PreconditionRequiredError,
    VersionConflictError,
)
from ...flags import require_capability
from ...models import AgentRun, WorkItem, utc_now
from ..domain import ACTIVE_RUN_STATUSES, validate_run_transition
from .base import _audit_run, _authorize, _aware, _get_agent, _update_run, get_run, logger
from .escalate import _escalate, _Escalation
from .terminate import _cancel_tree, _terminate

__all__ = [
    "_check_not_overdue", "expire_overdue_runs", "overdue_run_condition", "transition_run",
]


def _check_not_overdue(run: AgentRun) -> None:
    if _aware(run.deadline_at) <= utc_now():
        raise ConflictError("Agent run deadline has passed")


async def transition_run(
    session: AsyncSession,
    context: RequestContext,
    run_id: str,
    action: str,
    expected_version: int | None,
) -> AgentRun:
    if expected_version is None:
        raise PreconditionRequiredError("If-Match header is required")
    run = await get_run(session, context, run_id)
    _authorize(context, run, allow_manage=True)
    if run.version != expected_version:
        raise VersionConflictError("record_version_conflict")
    if action == "pause":
        validate_run_transition(run.status, "paused")
        await _update_run(session, run, status="paused")
        await _audit_run(session, context, run, "agent.run.paused")
    elif action == "resume":
        await require_capability(session, context, "agents", operation="agent.run.resume")
        validate_run_transition(run.status, "running")
        agent = await _get_agent(session, run.tenant_id, run.agent_id)
        if agent is None or agent.status != "active":
            raise ConflictError("Agent is not active")
        _check_not_overdue(run)
        if run.status == "waiting_human":
            item = await session.scalar(
                select(WorkItem).where(
                    WorkItem.id == run.escalation_work_item_id,
                    WorkItem.tenant_id == run.tenant_id,
                )
            )
            if item is None or item.status != "completed":
                raise ConflictError("The escalation work item must be completed before resuming")
        await _update_run(
            session,
            run,
            status="running",
            escalation_work_item_id=None,
            escalation_reason=None,
        )
        await _audit_run(session, context, run, "agent.run.resumed")
    elif action == "cancel":
        await _cancel_tree(session, context, run)
    else:
        raise InvalidRequestError(f"Unsupported run action: {action}")
    await session.commit()
    await session.refresh(run)
    return run


def overdue_run_condition(now: datetime) -> ColumnElement[bool]:
    """Active runs past their deadline. Shared by the sweep and the worker's discovery."""
    return AgentRun.status.in_(ACTIVE_RUN_STATUSES) & (AgentRun.deadline_at <= now)


async def expire_overdue_runs(session: AsyncSession, context: RequestContext) -> int:
    """Fail runs past their deadline so a crashed or stalled driver can never strand one."""
    runs = list(
        await session.scalars(
            select(AgentRun).where(
                AgentRun.tenant_id == context.tenant_id, overdue_run_condition(utc_now())
            )
        )
    )
    expired = 0
    for candidate in runs:
        run_id = candidate.id
        try:
            run = await session.get_one(AgentRun, run_id)
            if run.status == "waiting_human":
                await _terminate(session, context, run, "failed", "deadline_exceeded")
            else:
                await _escalate(
                    session,
                    context,
                    run,
                    _Escalation(
                        reason="deadline_exceeded",
                        summary="The run passed its deadline before reaching a terminal state.",
                        next_steps=["Review partial results and re-run or close the objective."],
                        run_status="failed",
                    ),
                )
            await session.commit()
            expired += 1
        except Exception:
            await session.rollback()
            logger.exception("could not expire agent run %s", run_id)
    return expired
