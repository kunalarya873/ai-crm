from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.deps import RequestContext, require_permission
from ..db import get_session
from ..flags import effective_flags, set_flag
from ..members import add_member, list_members, update_member
from ..permissions import Permission
from ..schemas import (
    FeatureFlagRead,
    FeatureFlagUpdate,
    MemberCreate,
    MemberRead,
    MemberUpdate,
)
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
