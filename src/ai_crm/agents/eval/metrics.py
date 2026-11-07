from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from ...models import AgentMessage, AgentRun, AgentStep
from .scenarios import Expect

FAILED_STEP_STATUSES = frozenset({"rejected", "escalated"})


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def tree_metrics(
    root_id: str,
    runs: Sequence[AgentRun],
    steps: Sequence[AgentStep],
    messages: Sequence[AgentMessage],
    *,
    cost_per_1k_micros: int,
) -> dict[str, Any]:
    root = next(run for run in runs if run.id == root_id)
    proposals = {step.action_proposal_id for step in steps if step.action_proposal_id}
    tokens = sum(step.tokens for step in steps)
    first_step_at: dict[str, datetime] = {}
    for step in steps:
        current = first_step_at.get(step.run_id)
        if current is None or _aware(step.created_at) < current:
            first_step_at[step.run_id] = _aware(step.created_at)
    latencies = [
        (first_step_at[message.to_run_id] - _aware(message.created_at)).total_seconds() * 1000
        for message in messages
        if message.kind == "delegation"
        and message.to_run_id is not None
        and message.to_run_id in first_step_at
    ]
    return {
        "root_status": root.status,
        "runs": len(runs),
        "steps": len(steps),
        "proposals": len(proposals),
        "failed_tool_calls": sum(1 for s in steps if s.status in FAILED_STEP_STATUSES),
        "duplicate_work": sum(
            1
            for s in steps
            if s.output.get("deduplicated") is True or s.error_code == "duplicate_ownership"
        ),
        "human_interventions": len(
            {run.escalation_work_item_id for run in runs if run.escalation_work_item_id}
        ),
        "escalation_reasons": sorted(
            {run.escalation_reason for run in runs if run.escalation_reason}
        ),
        "handoffs": len(latencies),
        "handoff_latency_ms": round(sum(latencies) / len(latencies), 3) if latencies else None,
        "tokens": tokens,
        "cost_micros": tokens * cost_per_1k_micros // 1000,
    }


def task_success(metrics: dict[str, Any], expect: Expect) -> bool:
    reasons = set(metrics["escalation_reasons"])
    wanted = {expect.escalation} if expect.escalation else set()
    return metrics["proposals"] == expect.proposals and reasons == wanted
