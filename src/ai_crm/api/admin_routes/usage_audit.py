from datetime import datetime
from typing import Annotated, Any

from fastapi import Depends, Query, Response

from ...api.deps import RequestContext, require_permission
from ...audit_query import query_audit_events
from ...export import export_rows
from ...permissions import Permission
from ...retention import purge_telemetry
from ...schemas import (
    AdminUsageRead,
    AuditEventRead,
    RetentionPurgeRequest,
    RetentionPurgeResult,
)
from ...usage import tenant_usage
from .base import SessionDependency, router

__all__ = [
    "AuditReadContext", "ExportContext", "RetentionContext", "UsageReadContext",
    "audit_events_endpoint", "export_endpoint", "retention_purge_endpoint",
    "tenant_usage_endpoint",
]


UsageReadContext = Annotated[
    RequestContext, Depends(require_permission(Permission.ADMIN_USAGE_READ))
]


@router.get("/admin/usage", response_model=AdminUsageRead, tags=["admin"])
async def tenant_usage_endpoint(
    session: SessionDependency, context: UsageReadContext
) -> AdminUsageRead:
    return await tenant_usage(session, context)


AuditReadContext = Annotated[
    RequestContext, Depends(require_permission(Permission.ADMIN_AUDIT_READ))
]


ExportContext = Annotated[RequestContext, Depends(require_permission(Permission.ADMIN_EXPORT))]


RetentionContext = Annotated[
    RequestContext, Depends(require_permission(Permission.ADMIN_RETENTION_MANAGE))
]


@router.get("/admin/audit-events", response_model=list[AuditEventRead], tags=["admin"])
async def audit_events_endpoint(
    response: Response,
    session: SessionDependency,
    context: AuditReadContext,
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(default=None, max_length=50),
    actor_id: str | None = Query(default=None, max_length=100),
    entity_type: str | None = Query(default=None, max_length=100),
    entity_id: str | None = Query(default=None, max_length=100),
    action: str | None = Query(default=None, max_length=100),
    outcome: str | None = Query(default=None, max_length=30),
    correlation_id: str | None = Query(default=None, max_length=100),
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[AuditEventRead]:
    rows = await query_audit_events(
        session,
        context,
        limit=limit,
        cursor=cursor,
        actor_id=actor_id,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        outcome=outcome,
        correlation_id=correlation_id,
        since=since,
        until=until,
    )
    items = rows[:limit]
    if len(rows) > limit:
        response.headers["X-Next-Cursor"] = str(items[-1].id)
    return [AuditEventRead.model_validate(item) for item in items]


@router.get("/admin/export/{resource}", response_model=list[dict[str, Any]], tags=["admin"])
async def export_endpoint(
    resource: str,
    response: Response,
    session: SessionDependency,
    context: ExportContext,
    limit: int = Query(default=100, ge=1, le=500),
    cursor: str | None = Query(default=None, max_length=300),
) -> list[dict[str, Any]]:
    items, next_cursor = await export_rows(session, context, resource, limit=limit, cursor=cursor)
    if next_cursor is not None:
        response.headers["X-Next-Cursor"] = next_cursor
    return items


@router.post("/admin/retention/purge", response_model=RetentionPurgeResult, tags=["admin"])
async def retention_purge_endpoint(
    payload: RetentionPurgeRequest, session: SessionDependency, context: RetentionContext
) -> RetentionPurgeResult:
    return await purge_telemetry(session, context, payload)
