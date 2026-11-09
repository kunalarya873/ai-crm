from datetime import datetime

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import RequestContext
from ...domain import InvalidRequestError
from ...models import ActionExecution, AIRun, utc_now
from ...schemas import SloReport
from ..service import _window
from .api import _api_slis
from .definitions import MAX_SLO_WINDOW, slo_definitions
from .freshness import _overdue_agent_runs, _search_freshness, _sync_freshness
from .queues import _job_success, _queue_age
from .results import _result

__all__ = [
    "_action_completion", "_ai_rates", "evaluate_slos",
]


async def _action_completion(
    session: AsyncSession, tenant_id: str, start: datetime, end: datetime
) -> tuple[float | None, dict]:
    rows = await session.execute(
        select(ActionExecution.status, func.count())
        .where(
            ActionExecution.tenant_id == tenant_id,
            ActionExecution.created_at >= start,
            ActionExecution.created_at <= end,
            ActionExecution.status.in_({"succeeded", "failed", "recoverable", "uncertain"}),
        )
        .group_by(ActionExecution.status)
    )
    counts = {status: count for status, count in rows.all()}
    finished = sum(counts.values())
    if not finished:
        return None, {"finished_executions": 0}
    return counts.get("succeeded", 0) / finished, {"finished_executions": finished, **counts}


async def _ai_rates(
    session: AsyncSession, tenant_id: str, start: datetime, end: datetime
) -> tuple[float | None, float | None, dict]:
    total, fallbacks, latency, samples = (
        await session.execute(
            select(
                func.count(),
                func.coalesce(func.sum(case((AIRun.status == "fallback", 1), else_=0)), 0),
                func.avg(AIRun.latency_ms),
                func.count(AIRun.latency_ms),
            ).where(
                AIRun.tenant_id == tenant_id,
                AIRun.created_at >= start,
                AIRun.created_at <= end,
            )
        )
    ).one()
    detail = {"total_runs": total, "fallback_runs": int(fallbacks), "latency_samples": samples}
    return (
        (fallbacks / total) if total else None,
        float(latency) if latency is not None else None,
        detail,
    )


async def evaluate_slos(
    session: AsyncSession,
    context: RequestContext,
    *,
    window_start: datetime | None = None,
    window_end: datetime | None = None,
) -> SloReport:
    start, end = _window(window_start, window_end)
    if end - start > MAX_SLO_WINDOW:
        raise InvalidRequestError(f"SLO windows are limited to {MAX_SLO_WINDOW.days} days")
    now = utc_now()
    tenant_id = context.tenant_id
    queue_age, queue_detail = await _queue_age(session, tenant_id, now)
    job_rate, job_detail = await _job_success(session, tenant_id, start, end)
    sync_age, sync_detail = await _sync_freshness(session, tenant_id, now)
    stale_ratio, stale_detail = await _search_freshness(session, tenant_id, now)
    completion, completion_detail = await _action_completion(session, tenant_id, start, end)
    fallback_rate, avg_latency, ai_detail = await _ai_rates(session, tenant_id, start, end)
    availability, error_rate, p95, api_detail = await _api_slis(session, tenant_id, start, end)
    values: dict[str, tuple[float | None, dict]] = {
        "queue_age_seconds": (queue_age, queue_detail),
        "job_success_rate": (job_rate, job_detail),
        "sync_freshness_seconds": (sync_age, sync_detail),
        "search_freshness_ratio": (stale_ratio, stale_detail),
        "action_completion_rate": (completion, completion_detail),
        "ai_fallback_rate": (fallback_rate, ai_detail),
        "ai_avg_latency_ms": (avg_latency, ai_detail),
        "agent_overdue_runs": (await _overdue_agent_runs(session, tenant_id, now), {}),
        "api_availability": (availability, api_detail),
        "api_latency_p95_ms": (p95, api_detail),
        "api_error_rate": (error_rate, api_detail),
    }
    results = [
        _result(definition, *values.get(definition.key, (None, {})))
        for definition in slo_definitions()
    ]
    return SloReport(window_start=start, window_end=end, slos=results)
