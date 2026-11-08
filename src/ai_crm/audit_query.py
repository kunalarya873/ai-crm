from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .api.deps import RequestContext
from .audit import record_audit
from .domain import InvalidRequestError
from .models import AuditEvent


def decode_audit_cursor(cursor: str) -> int:
    try:
        value = int(cursor)
    except ValueError as error:
        raise InvalidRequestError("Invalid pagination cursor") from error
    if value < 1:
        raise InvalidRequestError("Invalid pagination cursor")
    return value


async def query_audit_events(
    session: AsyncSession,
    context: RequestContext,
    *,
    limit: int,
    cursor: str | None = None,
    actor_id: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    action: str | None = None,
    outcome: str | None = None,
    correlation_id: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> Sequence[AuditEvent]:
    """Newest-first, tenant-scoped. Fetches limit + 1 rows so the router can detect a next page."""
    if since is not None and since.tzinfo is None:
        since = since.replace(tzinfo=UTC)
    if until is not None and until.tzinfo is None:
        until = until.replace(tzinfo=UTC)
    if since is not None and until is not None and since > until:
        raise InvalidRequestError("since must not be after until")
    statement = select(AuditEvent).where(AuditEvent.tenant_id == context.tenant_id)
    for column, value in (
        (AuditEvent.actor_id, actor_id),
        (AuditEvent.entity_type, entity_type),
        (AuditEvent.entity_id, entity_id),
        (AuditEvent.action, action),
        (AuditEvent.outcome, outcome),
        (AuditEvent.correlation_id, correlation_id),
    ):
        if value is not None:
            statement = statement.where(column == value)
    if since is not None:
        statement = statement.where(AuditEvent.created_at >= since)
    if until is not None:
        statement = statement.where(AuditEvent.created_at <= until)
    if cursor is not None:
        statement = statement.where(AuditEvent.id < decode_audit_cursor(cursor))
    rows = (
        await session.scalars(statement.order_by(AuditEvent.id.desc()).limit(limit + 1))
    ).all()
    await record_audit(
        session,
        context,
        "audit.queried",
        "audit_event",
        "query",
        details={
            "filters": {
                key: value
                for key, value in {
                    "actor_id": actor_id,
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "action": action,
                    "outcome": outcome,
                    "correlation_id": correlation_id,
                }.items()
                if value is not None
            },
            "returned": min(len(rows), limit),
        },
    )
    await session.commit()
    return rows
