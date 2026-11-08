from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.deps import RequestContext, require_permission
from ..audit_query import query_audit_events
from ..db import get_session
from ..export import export_rows
from ..flags import effective_flags, set_flag
from ..members import add_member, list_members, update_member
from ..permissions import Permission
from ..retention import purge_telemetry
from ..schemas import (
    AdminUsageRead,
    AuditEventRead,
    FeatureFlagRead,
    FeatureFlagUpdate,
    MemberCreate,
    MemberRead,
    MemberUpdate,
    RetentionPurgeRequest,
    RetentionPurgeResult,
)
from ..usage import tenant_usage
from .routes import parse_if_match, set_etag

router = APIRouter()
SessionDependency = Annotated[AsyncSession, Depends(get_session)]
ReadContext = Annotated[
    RequestContext, Depends(require_permission(Permission.ADMIN_MEMBERS_READ))
]
ManageContext = Annotated[
    RequestContext, Depends(require_permission(Permission.ADMIN_MEMBERS_MANAGE))
]


@router.get("/admin/members", response_model=list[MemberRead], tags=["admin"])
async def list_members_endpoint(
    session: SessionDependency,
    context: ReadContext,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[MemberRead]:
    return await list_members(session, context, limit, offset)


@router.post(
    "/admin/members",
    response_model=MemberRead,
    status_code=status.HTTP_201_CREATED,
    tags=["admin"],
)
async def add_member_endpoint(
    payload: MemberCreate,
    response: Response,
    session: SessionDependency,
    context: ManageContext,
) -> MemberRead:
    member = await add_member(session, context, payload)
    set_etag(response, member.version)
    return member


@router.patch("/admin/members/{membership_id}", response_model=MemberRead, tags=["admin"])
async def update_member_endpoint(
    membership_id: str,
    payload: MemberUpdate,
    response: Response,
    session: SessionDependency,
    context: ManageContext,
    if_match: Annotated[str | None, Header()] = None,
) -> MemberRead:
    member = await update_member(
        session, context, membership_id, payload, parse_if_match(if_match)
    )
    set_etag(response, member.version)
    return member


FlagsReadContext = Annotated[
    RequestContext, Depends(require_permission(Permission.ADMIN_FLAGS_READ))
]
FlagsManageContext = Annotated[
    RequestContext, Depends(require_permission(Permission.ADMIN_FLAGS_MANAGE))
]


@router.get("/admin/feature-flags", response_model=list[FeatureFlagRead], tags=["admin"])
async def list_feature_flags_endpoint(
    session: SessionDependency, context: FlagsReadContext
) -> list[FeatureFlagRead]:
    return await effective_flags(session, context.tenant_id)


@router.put("/admin/feature-flags/{flag}", response_model=FeatureFlagRead, tags=["admin"])
async def set_feature_flag_endpoint(
    flag: str,
    payload: FeatureFlagUpdate,
    response: Response,
    session: SessionDependency,
    context: FlagsManageContext,
    if_match: Annotated[str | None, Header()] = None,
) -> FeatureFlagRead:
    result = await set_flag(
        session,
        context,
        flag,
        enabled=payload.enabled,
        reason=payload.reason,
        expected_version=parse_if_match(if_match, minimum=0),
    )
    set_etag(response, result.version)
    return result


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
