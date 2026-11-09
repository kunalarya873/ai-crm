from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import RequestContext
from ...models import AgentMessage, AgentRun, utc_now
from ..domain import ACTIVE_RUN_STATUSES, validate_run_transition
from .base import _audit_run, _update_run

__all__ = [
    "_active_descendants", "_cancel_tree", "_stop_descendants", "_terminate",
]


async def _terminate(
    session: AsyncSession,
    context: RequestContext,
    run: AgentRun,
    status: str,
    reason: str,
    *,
    extra_values: dict[str, Any] | None = None,
    notify_parent: bool = True,
) -> None:
    validate_run_transition(run.status, status)
    await _update_run(
        session,
        run,
        status=status,
        terminal_reason=reason,
        completed_at=utc_now(),
        **(extra_values or {}),
    )
    await _audit_run(session, context, run, f"agent.run.{status}", reason=reason)
    if status in {"cancelled", "failed"}:
        await _stop_descendants(
            session, context, run, "parent_cancelled" if status == "cancelled" else "parent_failed"
        )
    if notify_parent and run.parent_run_id:
        session.add(
            AgentMessage(
                tenant_id=run.tenant_id,
                root_run_id=run.root_run_id,
                from_run_id=run.id,
                to_run_id=run.parent_run_id,
                kind="result",
                body={"status": status, "reason": reason, "objective": run.objective},
            )
        )


async def _active_descendants(session: AsyncSession, run: AgentRun) -> list[AgentRun]:
    # Walk every run in the tree: an active grandchild can sit below a finished child.
    tree = list(
        await session.scalars(
            select(AgentRun).where(
                AgentRun.tenant_id == run.tenant_id,
                AgentRun.root_run_id == run.root_run_id,
            )
        )
    )
    doomed = {run.id}
    grew = True
    while grew:
        grew = False
        for candidate in tree:
            if candidate.parent_run_id in doomed and candidate.id not in doomed:
                doomed.add(candidate.id)
                grew = True
    return [
        candidate
        for candidate in tree
        if candidate.id in doomed
        and candidate.id != run.id
        and candidate.status in ACTIVE_RUN_STATUSES
    ]


async def _stop_descendants(
    session: AsyncSession, context: RequestContext, run: AgentRun, reason: str
) -> None:
    for descendant in await _active_descendants(session, run):
        if descendant.status not in ACTIVE_RUN_STATUSES:
            continue  # already stopped by an earlier cascade in this loop
        await _terminate(
            session, context, descendant, "cancelled", reason, notify_parent=False
        )


async def _cancel_tree(session: AsyncSession, context: RequestContext, run: AgentRun) -> None:
    validate_run_transition(run.status, "cancelled")
    await _terminate(session, context, run, "cancelled", "cancelled_by_user")
