from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import RequestContext
from ...models import (
    ActionExecution,
    AIFeedback,
    AIRun,
    DurableJob,
    OperationalEvent,
    WorkItem,
)
from .guards import _as_utc

__all__ = [
    "_compute_metrics",
]


async def _compute_metrics(
    session: AsyncSession,
    context: RequestContext,
    start: datetime,
    end: datetime,
) -> list[tuple[str, float, str, str, dict[str, object]]]:
    ai_runs = list(
        await session.scalars(
            select(AIRun).where(
                AIRun.tenant_id == context.tenant_id,
                AIRun.created_at >= start,
                AIRun.created_at <= end,
            )
        )
    )
    feedback = list(
        await session.scalars(
            select(AIFeedback).where(
                AIFeedback.tenant_id == context.tenant_id,
                AIFeedback.created_at >= start,
                AIFeedback.created_at <= end,
            )
        )
    )
    actions = list(
        await session.scalars(
            select(ActionExecution).where(
                ActionExecution.tenant_id == context.tenant_id,
                ActionExecution.created_at >= start,
                ActionExecution.created_at <= end,
            )
        )
    )
    jobs = list(
        await session.scalars(
            select(DurableJob).where(
                DurableJob.tenant_id == context.tenant_id,
                DurableJob.created_at >= start,
                DurableJob.created_at <= end,
            )
        )
    )
    work_items = list(
        await session.scalars(select(WorkItem).where(WorkItem.tenant_id == context.tenant_id))
    )
    overdue = [
        item
        for item in work_items
        if (due_at := _as_utc(item.due_at)) is not None and due_at <= end
        and item.status not in {"completed", "cancelled"}
    ]
    total_ai = len(ai_runs)
    fallback_ai = sum(run.status == "fallback" for run in ai_runs)
    intervention = sum(item.feedback_type in {"edited", "corrected"} for item in feedback)
    total_actions = len(actions)
    failed_actions = sum(item.status in {"failed", "recoverable", "uncertain"} for item in actions)
    total_jobs = len(jobs)
    failed_jobs = sum(item.status in {"failed", "dead_letter"} for item in jobs)
    latency_values = [run.latency_ms for run in ai_runs if run.latency_ms is not None]
    event_count = await session.scalar(
        select(func.count(OperationalEvent.id)).where(
            OperationalEvent.tenant_id == context.tenant_id,
            OperationalEvent.created_at >= start,
            OperationalEvent.created_at <= end,
        )
    )
    return [
        ("ai.runs", float(total_ai), "count", "complete", {}),
        (
            "ai.fallback_rate",
            fallback_ai / total_ai if total_ai else 0.0,
            "ratio",
            "complete" if total_ai else "incomplete",
            {"fallback_runs": fallback_ai, "total_runs": total_ai},
        ),
        (
            "ai.cost_micros",
            float(sum(run.estimated_cost_micros for run in ai_runs)),
            "micros",
            "complete",
            {},
        ),
        (
            "ai.avg_latency_ms",
            sum(latency_values) / len(latency_values) if latency_values else 0.0,
            "milliseconds",
            "complete" if latency_values else "incomplete",
            {"sample_count": len(latency_values)},
        ),
        (
            "ai.human_intervention_rate",
            intervention / total_ai if total_ai else 0.0,
            "ratio",
            "complete" if total_ai else "incomplete",
            {"interventions": intervention, "total_runs": total_ai},
        ),
        ("actions.executions", float(total_actions), "count", "complete", {}),
        (
            "actions.failure_rate",
            failed_actions / total_actions if total_actions else 0.0,
            "ratio",
            "complete" if total_actions else "incomplete",
            {"failed_executions": failed_actions, "total_executions": total_actions},
        ),
        ("jobs.failed", float(failed_jobs), "count", "complete", {"total_jobs": total_jobs}),
        ("work.overdue", float(len(overdue)), "count", "complete", {}),
        ("events.count", float(event_count or 0), "count", "complete", {}),
    ]
