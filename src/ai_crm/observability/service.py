from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.deps import RequestContext
from ..audit import record_audit
from ..config import settings
from ..domain import ConflictError, InvalidRequestError, NotFoundError
from ..models import (
    ActionExecution,
    AIFeedback,
    AIRun,
    DurableJob,
    IntegrationConnection,
    MetricObservation,
    OperationalAlert,
    OperationalEvent,
    Opportunity,
    WorkItem,
    utc_now,
)
from ..permissions import Permission
from ..schemas import (
    AlertDecision,
    MetricSummaryItem,
    ObservabilitySummary,
    ProactiveCheckResponse,
)


def _require_manage(context: RequestContext) -> None:
    if Permission.OBSERVABILITY_MANAGE not in context.permissions:
        raise InvalidRequestError("Observability management permission is required")


def _require_read(context: RequestContext) -> None:
    if Permission.OBSERVABILITY_READ not in context.permissions:
        raise InvalidRequestError("Observability read permission is required")


def _window(
    window_start: datetime | None,
    window_end: datetime | None,
) -> tuple[datetime, datetime]:
    end = window_end or utc_now()
    start = window_start or end - timedelta(hours=24)
    if start.tzinfo is None or end.tzinfo is None:
        raise InvalidRequestError("Metric windows must include a timezone")
    if start >= end:
        raise InvalidRequestError("Metric window start must be before window end")
    return start.astimezone(UTC), end.astimezone(UTC)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


async def list_metrics(
    session: AsyncSession,
    context: RequestContext,
    *,
    metric_key: str | None = None,
    limit: int,
    offset: int,
) -> list[MetricObservation]:
    _require_read(context)
    statement = select(MetricObservation).where(MetricObservation.tenant_id == context.tenant_id)
    if metric_key:
        statement = statement.where(MetricObservation.metric_key == metric_key)
    result = await session.scalars(
        statement.order_by(MetricObservation.created_at.desc()).offset(offset).limit(limit)
    )
    return list(result)


async def list_events(
    session: AsyncSession,
    context: RequestContext,
    *,
    event_type: str | None = None,
    trace_id: str | None = None,
    limit: int,
    offset: int,
) -> list[OperationalEvent]:
    _require_read(context)
    statement = select(OperationalEvent).where(OperationalEvent.tenant_id == context.tenant_id)
    if event_type:
        statement = statement.where(OperationalEvent.event_type == event_type)
    if trace_id:
        statement = statement.where(OperationalEvent.trace_id == trace_id)
    result = await session.scalars(
        statement.order_by(OperationalEvent.created_at.desc()).offset(offset).limit(limit)
    )
    return list(result)


async def list_alerts(
    session: AsyncSession,
    context: RequestContext,
    *,
    alert_status: str | None,
    alert_type: str | None,
    limit: int,
    offset: int,
) -> list[OperationalAlert]:
    _require_read(context)
    statement = select(OperationalAlert).where(OperationalAlert.tenant_id == context.tenant_id)
    if alert_status:
        if alert_status not in {"open", "acknowledged", "resolved", "suppressed"}:
            raise InvalidRequestError(f"Unsupported alert status: {alert_status}")
        statement = statement.where(OperationalAlert.status == alert_status)
    if alert_type:
        if alert_type not in {"system", "business"}:
            raise InvalidRequestError(f"Unsupported alert type: {alert_type}")
        statement = statement.where(OperationalAlert.alert_type == alert_type)
    result = await session.scalars(
        statement.order_by(OperationalAlert.created_at.desc()).offset(offset).limit(limit)
    )
    return list(result)


async def get_alert(
    session: AsyncSession,
    context: RequestContext,
    alert_id: str,
) -> OperationalAlert:
    _require_read(context)
    alert = await session.scalar(
        select(OperationalAlert).where(
            OperationalAlert.id == alert_id,
            OperationalAlert.tenant_id == context.tenant_id,
        )
    )
    if alert is None:
        raise NotFoundError("Operational alert not found")
    return alert


async def acknowledge_alert(
    session: AsyncSession,
    context: RequestContext,
    alert_id: str,
    payload: AlertDecision,
) -> OperationalAlert:
    _require_manage(context)
    alert = await get_alert(session, context, alert_id)
    if alert.status == "resolved":
        raise ConflictError("Resolved alerts cannot be acknowledged")
    alert.status = "acknowledged"
    alert.acknowledged_by = context.actor_id
    alert.acknowledged_at = utc_now()
    await record_audit(
        session,
        context,
        "observability.alert.acknowledged",
        "operational_alert",
        alert.id,
        details={"note": payload.note},
    )
    await session.commit()
    await session.refresh(alert)
    return alert


async def resolve_alert(
    session: AsyncSession,
    context: RequestContext,
    alert_id: str,
    payload: AlertDecision,
) -> OperationalAlert:
    _require_manage(context)
    alert = await get_alert(session, context, alert_id)
    if alert.status == "resolved":
        return alert
    alert.status = "resolved"
    alert.resolved_by = context.actor_id
    alert.resolved_at = utc_now()
    alert.resolution_note = payload.note
    await record_audit(
        session,
        context,
        "observability.alert.resolved",
        "operational_alert",
        alert.id,
        details={"note": payload.note},
    )
    await session.commit()
    await session.refresh(alert)
    return alert


async def collect_metrics(
    session: AsyncSession,
    context: RequestContext,
    *,
    window_start: datetime | None = None,
    window_end: datetime | None = None,
) -> list[MetricObservation]:
    _require_manage(context)
    start, end = _window(window_start, window_end)
    metrics = await _compute_metrics(session, context, start, end)
    observations: list[MetricObservation] = []
    for metric_key, value, unit, quality, dimensions in metrics:
        existing = await session.scalar(
            select(MetricObservation).where(
                MetricObservation.tenant_id == context.tenant_id,
                MetricObservation.metric_key == metric_key,
                MetricObservation.window_start == start,
                MetricObservation.window_end == end,
            )
        )
        if existing is None:
            existing = MetricObservation(
                tenant_id=context.tenant_id,
                metric_key=metric_key,
                value=value,
                unit=unit,
                quality=quality,
                dimensions=dimensions,
                source_event_ids=[],
                window_start=start,
                window_end=end,
            )
            session.add(existing)
        else:
            existing.value = value
            existing.unit = unit
            existing.quality = quality
            existing.dimensions = dimensions
        observations.append(existing)
    await record_audit(
        session,
        context,
        "observability.metrics.collected",
        "metric_observation",
        context.correlation_id,
        details={"metric_count": len(metrics), "window_start": start, "window_end": end},
    )
    await session.commit()
    for observation in observations:
        await session.refresh(observation)
    return observations


async def summary(
    session: AsyncSession,
    context: RequestContext,
    *,
    window_start: datetime | None = None,
    window_end: datetime | None = None,
) -> ObservabilitySummary:
    _require_read(context)
    start, end = _window(window_start, window_end)
    metrics = await _compute_metrics(session, context, start, end)
    items = [
        MetricSummaryItem(
            metric_key=metric_key,
            value=value,
            unit=unit,
            quality=quality,
            dimensions=dimensions,
        )
        for metric_key, value, unit, quality, dimensions in metrics
    ]
    open_alerts = await session.scalar(
        select(func.count(OperationalAlert.id)).where(
            OperationalAlert.tenant_id == context.tenant_id,
            OperationalAlert.status.in_({"open", "acknowledged"}),
        )
    )
    return ObservabilitySummary(
        window_start=start,
        window_end=end,
        metrics=items,
        open_alerts=int(open_alerts or 0),
        incomplete_metrics=[
            item.metric_key for item in items if item.quality != "complete"
        ],
    )


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


async def run_proactive_checks(
    session: AsyncSession,
    context: RequestContext,
) -> ProactiveCheckResponse:
    _require_manage(context)
    now = utc_now()
    created = 0
    reopened = 0
    work_created = 0
    suppressed = 0
    alert_ids: list[str] = []

    overdue_items = list(
        await session.scalars(
            select(WorkItem).where(
                WorkItem.tenant_id == context.tenant_id,
                WorkItem.due_at.is_not(None),
                WorkItem.due_at < now,
                WorkItem.status.not_in({"completed", "cancelled"}),
            )
        )
    )
    for item in overdue_items:
        due_at = item.due_at
        if due_at is None:
            continue
        result = await _ensure_exception(
            session,
            context,
            rule_key="overdue_work_item",
            alert_type="business",
            severity="warning",
            title=f"Overdue work item: {item.title}",
            description="A work item is past due and still open.",
            related_type="work_item",
            related_id=item.id,
            evidence=[{"field": "due_at", "value": due_at.isoformat()}],
            now=now,
        )
        created += result[0]
        reopened += result[1]
        work_created += result[2]
        suppressed += result[3]
        if result[4]:
            alert_ids.append(result[4])

    inactive_before = now - timedelta(days=settings.proactive_inactive_opportunity_days)
    inactive_opportunities = list(
        await session.scalars(
            select(Opportunity).where(
                Opportunity.tenant_id == context.tenant_id,
                Opportunity.status == "open",
                Opportunity.archived_at.is_(None),
                Opportunity.updated_at < inactive_before,
            )
        )
    )
    for opportunity in inactive_opportunities:
        opportunity_updated_at = opportunity.updated_at
        result = await _ensure_exception(
            session,
            context,
            rule_key="inactive_opportunity",
            alert_type="business",
            severity="warning",
            title=f"Inactive opportunity: {opportunity.name}",
            description=(
                "An open opportunity has not changed within the configured activity "
                "window."
            ),
            related_type="opportunity",
            related_id=opportunity.id,
            evidence=[{"field": "updated_at", "value": opportunity_updated_at.isoformat()}],
            now=now,
        )
        created += result[0]
        reopened += result[1]
        work_created += result[2]
        suppressed += result[3]
        if result[4]:
            alert_ids.append(result[4])

    reauth_connections = list(
        await session.scalars(
            select(IntegrationConnection).where(
                IntegrationConnection.tenant_id == context.tenant_id,
                IntegrationConnection.status == "needs_reauth",
            )
        )
    )
    for connection in reauth_connections:
        result = await _ensure_exception(
            session,
            context,
            rule_key="connection_needs_reauth",
            alert_type="system",
            severity="warning",
            title=f"Integration needs re-authorisation: {connection.external_account_id}",
            description="Token refresh failed permanently; syncs and writes are paused.",
            related_type="integration_connection",
            related_id=connection.id,
            evidence=[{"field": "last_error_code", "value": connection.last_error_code}],
            now=now,
        )
        created += result[0]
        reopened += result[1]
        work_created += result[2]
        suppressed += result[3]
        if result[4]:
            alert_ids.append(result[4])

    failed_jobs = list(
        await session.scalars(
            select(DurableJob).where(
                DurableJob.tenant_id == context.tenant_id,
                DurableJob.status.in_({"failed", "dead_letter"}),
            )
        )
    )
    for job in failed_jobs:
        result = await _ensure_exception(
            session,
            context,
            rule_key="failed_job",
            alert_type="system",
            severity="high",
            title=f"Failed job: {job.job_type}",
            description=job.error_detail or "A durable job requires operator review.",
            related_type="durable_job",
            related_id=job.id,
            evidence=[{"field": "error_code", "value": job.error_code}],
            now=now,
        )
        created += result[0]
        reopened += result[1]
        work_created += result[2]
        suppressed += result[3]
        if result[4]:
            alert_ids.append(result[4])

    failed_actions = list(
        await session.scalars(
            select(ActionExecution).where(
                ActionExecution.tenant_id == context.tenant_id,
                ActionExecution.status.in_({"failed", "recoverable", "uncertain"}),
            )
        )
    )
    for execution in failed_actions:
        result = await _ensure_exception(
            session,
            context,
            rule_key="failed_action",
            alert_type="system",
            severity="high",
            title=f"Action requires review: {execution.action_type}",
            description=execution.error_detail or "An action execution requires operator review.",
            related_type="action_execution",
            related_id=execution.id,
            evidence=[
                {"field": "status", "value": execution.status},
                {"field": "error_code", "value": execution.error_code},
            ],
            now=now,
        )
        created += result[0]
        reopened += result[1]
        work_created += result[2]
        suppressed += result[3]
        if result[4]:
            alert_ids.append(result[4])

    await record_audit(
        session,
        context,
        "observability.proactive_checks.completed",
        "proactive_check",
        context.correlation_id,
        details={
            "alerts_created": created,
            "alerts_reopened": reopened,
            "work_items_created": work_created,
            "suppressed_duplicates": suppressed,
        },
    )
    await session.commit()
    return ProactiveCheckResponse(
        checked_at=now,
        alerts_created=created,
        alerts_reopened=reopened,
        work_items_created=work_created,
        suppressed_duplicates=suppressed,
        alert_ids=alert_ids,
    )


async def _ensure_exception(
    session: AsyncSession,
    context: RequestContext,
    *,
    rule_key: str,
    alert_type: str,
    severity: str,
    title: str,
    description: str,
    related_type: str,
    related_id: str,
    evidence: list[dict[str, object]],
    now: datetime,
) -> tuple[int, int, int, int, str | None]:
    dedup_key = f"{rule_key}:{related_type}:{related_id}"
    alert = await session.scalar(
        select(OperationalAlert).where(
            OperationalAlert.tenant_id == context.tenant_id,
            OperationalAlert.dedup_key == dedup_key,
        )
    )
    if alert is not None and alert.status in {"open", "acknowledged"}:
        return 0, 0, 0, 1, alert.id
    reopened = 1 if alert is not None and alert.status == "resolved" else 0
    work_item_id = alert.work_item_id if alert is not None else None
    work_created = 0
    if work_item_id is None:
        work_item = WorkItem(
            tenant_id=context.tenant_id,
            item_type="escalation",
            title=f"Review exception: {title}",
            description=description,
            status="open",
            priority=80,
            owner_id=context.actor_id,
            source=f"proactive:{rule_key}",
            created_by=context.actor_id,
        )
        session.add(work_item)
        await session.flush()
        work_item_id = work_item.id
        work_created = 1
    if alert is None:
        alert = OperationalAlert(
            tenant_id=context.tenant_id,
            alert_type=alert_type,
            rule_key=rule_key,
            dedup_key=dedup_key,
            severity=severity,
            status="open",
            title=title,
            description=description,
            related_type=related_type,
            related_id=related_id,
            evidence=evidence,
            work_item_id=work_item_id,
        )
        session.add(alert)
        await session.flush()
    else:
        alert.status = "open"
        alert.evidence = evidence
        alert.resolved_by = None
        alert.resolved_at = None
        alert.resolution_note = None
        alert.updated_at = now
    return 1 if reopened == 0 else 0, reopened, work_created, 0, alert.id
