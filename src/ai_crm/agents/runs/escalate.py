import json
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import RequestContext
from ...models import AgentMessage, AgentRun, AgentStep, WorkItem, utc_now
from ...schemas import WorkItemCreate
from ...work.items import create_work_item_in_session
from ..domain import TERMINAL_RUN_STATUSES, validate_run_transition
from .base import _audit_run, _update_run
from .terminate import _stop_descendants

__all__ = [
    "_Escalation", "_escalate",
]


@dataclass
class _Escalation:
    reason: str
    summary: str
    evidence: list[dict[str, Any]] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)
    run_status: str = "waiting_human"
    also_runs: list[str] = field(default_factory=list)


async def _escalate(
    session: AsyncSession,
    context: RequestContext,
    run: AgentRun,
    spec: _Escalation,
    *,
    step: AgentStep | None = None,
    extra_values: dict[str, Any] | None = None,
) -> WorkItem:
    """Hand the run to a human: a work item carrying the evidence, and a persisted message."""
    lines = [
        spec.summary,
        f"Agent: {run.agent_key} {run.agent_version}; run {run.id}; objective: {run.objective}",
    ]
    if step is not None:
        lines.append(f"Step: {step.id} ({step.step_type})")
    if spec.next_steps:
        lines.append("Proposed next steps: " + "; ".join(spec.next_steps))
    if spec.evidence:
        lines.append("Evidence: " + json.dumps(spec.evidence, default=str)[:4000])
    item = await create_work_item_in_session(
        session,
        context,
        WorkItemCreate(
            item_type="escalation",
            title=f"Agent escalation ({spec.reason}): {run.objective}"[:200],
            description="\n".join(lines)[:10000],
            priority=80,
            owner_id=run.owner_id,
            assignee_id=run.owner_id,
            source="agent.escalation",
        ),
    )
    terminal = spec.run_status in TERMINAL_RUN_STATUSES
    validate_run_transition(run.status, spec.run_status)
    await _update_run(
        session,
        run,
        status=spec.run_status,
        escalation_work_item_id=item.id,
        escalation_reason=spec.reason,
        terminal_reason=spec.reason if terminal else None,
        completed_at=utc_now() if terminal else None,
        **(extra_values or {}),
    )
    if terminal and run.parent_run_id:
        session.add(
            AgentMessage(
                tenant_id=run.tenant_id,
                root_run_id=run.root_run_id,
                from_run_id=run.id,
                to_run_id=run.parent_run_id,
                kind="result",
                body={"status": spec.run_status, "reason": spec.reason, "objective": run.objective},
            )
        )
    session.add(
        AgentMessage(
            tenant_id=run.tenant_id,
            root_run_id=run.root_run_id,
            from_run_id=run.id,
            to_run_id=None,
            kind="escalation",
            body={
                "reason": spec.reason,
                "work_item_id": item.id,
                "summary": spec.summary,
                "step_id": step.id if step else None,
            },
        )
    )
    await _audit_run(
        session, context, run, "agent.run.escalated", reason=spec.reason, work_item_id=item.id
    )
    if terminal:
        await _stop_descendants(session, context, run, "parent_" + spec.run_status)
    for other_id in spec.also_runs:
        other = await session.scalar(
            select(AgentRun).where(
                AgentRun.id == other_id,
                AgentRun.tenant_id == run.tenant_id,
                AgentRun.status.in_({"running", "paused"}),
            )
        )
        if other is not None:
            await _update_run(
                session,
                other,
                status="waiting_human",
                escalation_work_item_id=item.id,
                escalation_reason=spec.reason,
            )
            await _audit_run(
                session, context, other, "agent.run.escalated",
                reason=spec.reason, work_item_id=item.id,
            )
    return item
