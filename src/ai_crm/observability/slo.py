from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.deps import RequestContext
from ..config import settings
from ..domain import InvalidRequestError
from ..models import (
    ActionExecution,
    AgentRun,
    AIRun,
    DurableJob,
    IntegrationConnection,
    IntegrationSyncRun,
    KnowledgeSource,
    utc_now,
)
from ..schemas import SloRead, SloReport
from .service import _as_utc, _window

MAX_SLO_WINDOW = timedelta(days=31)
Comparison = Literal["lte", "gte"]


@dataclass(frozen=True)
class SloDefinition:
    key: str
    description: str
    unit: str
    comparison: Comparison
    target: float
    measurable: bool = True
    reason: str | None = None


NO_REQUEST_TELEMETRY = (
    "The backend does not persist per-request telemetry, so this cannot be measured yet."
)

def _slo(
    key: str, description: str, unit: str, comparison: Comparison, target: float
) -> SloDefinition:
    return SloDefinition(key, description, unit, comparison, target)


def _unmeasured(
    key: str, description: str, unit: str, comparison: Comparison, target: float
) -> SloDefinition:
    return SloDefinition(key, description, unit, comparison, target, False, NO_REQUEST_TELEMETRY)


def slo_definitions() -> tuple[SloDefinition, ...]:
    return (
        _slo("queue_age_seconds", "Oldest ready job waiting in the queue", "seconds", "lte", 300),
        _slo("job_success_rate", "Finished jobs that succeeded", "ratio", "gte", 0.99),
        _slo(
            "sync_freshness_seconds",
            "Worst time since the last successful sync of a connected connection",
            "seconds",
            "lte",
            2.0 * settings.integration_sync_interval_seconds,
        ),
        _slo(
            "search_freshness_ratio",
            "Searchable sources past their fresh-until date",
            "ratio",
            "lte",
            0.2,
        ),
        _slo(
            "action_completion_rate",
            "Action executions that completed successfully",
            "ratio",
            "gte",
            0.95,
        ),
        _slo("ai_fallback_rate", "AI runs that fell back to a safe response", "ratio", "lte", 0.05),
        _slo("ai_avg_latency_ms", "Average AI response time", "milliseconds", "lte", 2000),
        _slo("agent_overdue_runs", "Agent runs past their deadline", "count", "lte", 0),
        _unmeasured("api_availability", "API availability", "ratio", "gte", 0.999),
        _unmeasured("api_latency_p95_ms", "API p95 latency", "milliseconds", "lte", 500),
        _unmeasured("api_error_rate", "API 5xx error rate", "ratio", "lte", 0.01),
    )


def _status(
    definition: SloDefinition, value: float | None
) -> Literal["met", "breached", "no_data"]:
    if value is None:
        return "no_data"
    if definition.comparison == "lte":
        return "met" if value <= definition.target else "breached"
    return "met" if value >= definition.target else "breached"


def _result(
    definition: SloDefinition, value: float | None, detail: dict[str, object] | None = None
) -> SloRead:
    if not definition.measurable:
        status: Literal["met", "breached", "no_data", "not_measured"] = "not_measured"
        value = None
    else:
        status = _status(definition, value)
    return SloRead(
        key=definition.key,
        description=definition.description,
        unit=definition.unit,
        comparison=definition.comparison,
        target=definition.target,
        owner=settings.slo_owner,
        status=status,
        value=value,
        detail=detail or {},
        reason=definition.reason,
    )


async def _queue_age(session: AsyncSession, tenant_id: str, now: datetime) -> tuple[float, dict]:
    """Oldest work that is ready now: waiting jobs, plus running jobs whose lease has expired
    (a crashed worker), which the lease-reclaim logic also treats as ready."""
    waiting = await session.scalar(
        select(func.min(DurableJob.run_at)).where(
            DurableJob.tenant_id == tenant_id,
            DurableJob.status.in_({"queued", "retryable"}),
            DurableJob.run_at <= now,
        )
    )
    abandoned = await session.scalar(
        select(func.min(DurableJob.lease_expires_at)).where(
            DurableJob.tenant_id == tenant_id,
            DurableJob.status == "running",
            DurableJob.lease_expires_at <= now,
        )
    )
    candidates = [_as_utc(value) for value in (waiting, abandoned) if value is not None]
    if not candidates:
        return 0.0, {"ready_jobs": 0}
    oldest = min(c for c in candidates if c is not None)
    age = max((now - oldest).total_seconds(), 0.0)
    detail = {"oldest_ready_job_at": oldest.isoformat(), "abandoned_leases": abandoned is not None}
    return age, detail


async def _job_success(
    session: AsyncSession, tenant_id: str, start: datetime, end: datetime
) -> tuple[float | None, dict]:
    rows = await session.execute(
        select(DurableJob.status, func.count())
        .where(
            DurableJob.tenant_id == tenant_id,
            func.coalesce(DurableJob.completed_at, DurableJob.updated_at) >= start,
            func.coalesce(DurableJob.completed_at, DurableJob.updated_at) <= end,
            DurableJob.status.in_({"succeeded", "failed", "dead_letter"}),
        )
        .group_by(DurableJob.status)
    )
    counts = {status: count for status, count in rows.all()}
    finished = sum(counts.values())
    if not finished:
        return None, {"finished_jobs": 0}
    return counts.get("succeeded", 0) / finished, {"finished_jobs": finished, **counts}


async def _sync_freshness(
    session: AsyncSession, tenant_id: str, now: datetime
) -> tuple[float | None, dict]:
    connections = (
        await session.execute(
            select(IntegrationConnection.id, IntegrationConnection.created_at).where(
                IntegrationConnection.tenant_id == tenant_id,
                IntegrationConnection.status == "connected",
            )
        )
    ).all()
    if not connections:
        return None, {"connected_connections": 0}
    last_success = dict(
        (
            await session.execute(
                select(
                    IntegrationSyncRun.connection_id, func.max(IntegrationSyncRun.last_success_at)
                )
                .where(IntegrationSyncRun.connection_id.in_([c.id for c in connections]))
                .group_by(IntegrationSyncRun.connection_id)
            )
        ).all()
    )
    ages: dict[str, float] = {}
    for connection_id, created_at in connections:
        reference = _as_utc(last_success.get(connection_id)) or _as_utc(created_at)
        assert reference is not None
        ages[connection_id] = (now - reference).total_seconds()
    worst = max(ages, key=lambda key: ages[key])
    return ages[worst], {"connected_connections": len(connections), "worst_connection_id": worst}


async def _search_freshness(
    session: AsyncSession, tenant_id: str, now: datetime
) -> tuple[float | None, dict]:
    base = (
        KnowledgeSource.tenant_id == tenant_id,
        KnowledgeSource.status == "active",
        KnowledgeSource.searchable.is_(True),
        KnowledgeSource.fresh_until.is_not(None),
    )
    total = await session.scalar(select(func.count()).select_from(KnowledgeSource).where(*base))
    if not total:
        return None, {"sources_with_freshness": 0}
    stale = await session.scalar(
        select(func.count())
        .select_from(KnowledgeSource)
        .where(*base, KnowledgeSource.fresh_until < now)
    )
    return (stale or 0) / total, {"sources_with_freshness": total, "stale_sources": stale or 0}


async def _overdue_agent_runs(session: AsyncSession, tenant_id: str, now: datetime) -> float:
    count = await session.scalar(
        select(func.count())
        .select_from(AgentRun)
        .where(
            AgentRun.tenant_id == tenant_id,
            AgentRun.status.in_({"running", "paused", "waiting_human"}),
            AgentRun.deadline_at < now,
        )
    )
    return float(count or 0)


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
    values: dict[str, tuple[float | None, dict]] = {
        "queue_age_seconds": (queue_age, queue_detail),
        "job_success_rate": (job_rate, job_detail),
        "sync_freshness_seconds": (sync_age, sync_detail),
        "search_freshness_ratio": (stale_ratio, stale_detail),
        "action_completion_rate": (completion, completion_detail),
        "ai_fallback_rate": (fallback_rate, ai_detail),
        "ai_avg_latency_ms": (avg_latency, ai_detail),
        "agent_overdue_runs": (await _overdue_agent_runs(session, tenant_id, now), {}),
    }
    results = [
        _result(definition, *values.get(definition.key, (None, {})))
        for definition in slo_definitions()
    ]
    return SloReport(window_start=start, window_end=end, slos=results)
