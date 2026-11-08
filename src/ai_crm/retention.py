from datetime import timedelta
from typing import Any

from sqlalchemy import ColumnElement, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .api.deps import RequestContext
from .audit import record_audit
from .config import settings
from .domain import InvalidRequestError
from .models import MetricObservation, OperationalAlert, OperationalEvent, OutboxEvent, utc_now
from .schemas import RetentionPurgeRequest, RetentionPurgeResult


async def purge_telemetry(
    session: AsyncSession, context: RequestContext, payload: RetentionPurgeRequest
) -> RetentionPurgeResult:
    """Delete aged operational telemetry for the tenant. Audit events and CRM data are never
    touched; each table is capped at the configured batch size per call."""
    minimum = settings.observability_retention_days
    days = payload.older_than_days if payload.older_than_days is not None else minimum
    if days < minimum:
        raise InvalidRequestError(
            f"older_than_days must be at least the configured retention of {minimum} days"
        )
    cutoff = utc_now() - timedelta(days=days)
    tenant_id = context.tenant_id
    batch = settings.retention_purge_batch_size
    targets: dict[str, tuple[Any, Any, ColumnElement[bool]]] = {
        "operational_events": (
            OperationalEvent,
            OperationalEvent.created_at,
            OperationalEvent.created_at < cutoff,
        ),
        "metric_observations": (
            MetricObservation,
            MetricObservation.created_at,
            MetricObservation.created_at < cutoff,
        ),
        "resolved_alerts": (
            OperationalAlert,
            OperationalAlert.resolved_at,
            (OperationalAlert.status == "resolved") & (OperationalAlert.resolved_at < cutoff),
        ),
        "published_outbox_events": (
            OutboxEvent,
            OutboxEvent.published_at,
            OutboxEvent.published_at.is_not(None) & (OutboxEvent.published_at < cutoff),
        ),
    }
    counts: dict[str, int] = {}
    truncated = False
    for name, (model, order_column, condition) in targets.items():
        scope = (model.tenant_id == tenant_id) & condition
        total = int(await session.scalar(select(func.count()).select_from(model).where(scope)) or 0)
        if payload.dry_run:
            counts[name] = min(total, batch)
            truncated = truncated or total > batch
            continue
        ids = (
            await session.scalars(
                select(model.id).where(scope).order_by(order_column, model.id).limit(batch)
            )
        ).all()
        deleted = 0
        if ids:
            result = await session.execute(
                delete(model).where(model.tenant_id == tenant_id, model.id.in_(ids))
            )
            deleted = int(getattr(result, "rowcount", 0) or 0)
        counts[name] = deleted
        truncated = truncated or total > deleted
    if not payload.dry_run:
        await record_audit(
            session,
            context,
            "retention.purged",
            "retention",
            "telemetry",
            details={"older_than_days": days, "cutoff": cutoff.isoformat(), "counts": counts},
        )
    await session.commit()
    return RetentionPurgeResult(
        dry_run=payload.dry_run,
        cutoff=cutoff,
        older_than_days=days,
        counts=counts,
        batch_limit=batch,
        truncated=truncated,
    )
