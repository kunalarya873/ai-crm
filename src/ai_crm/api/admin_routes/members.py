from typing import Annotated

from fastapi import Header, Query, Response, status

from ...members import add_member, list_members, update_member
from ...schemas import MemberCreate, MemberRead, MemberUpdate
from ..routes import parse_if_match, set_etag
from .base import ManageContext, ReadContext, SessionDependency, router

__all__ = [
    "add_member_endpoint", "list_members_endpoint", "update_member_endpoint",
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
