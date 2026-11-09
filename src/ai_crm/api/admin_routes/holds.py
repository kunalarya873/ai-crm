from typing import Annotated

from fastapi import Depends, Query, status

from ...api.deps import RequestContext, require_permission
from ...lifecycle import create_hold, list_holds, release_hold
from ...permissions import Permission
from ...schemas import LegalHoldCreate, LegalHoldRead, LegalHoldRelease
from .base import SessionDependency, router

__all__ = [
    "HoldContext", "create_legal_hold_endpoint", "list_legal_holds_endpoint",
    "release_legal_hold_endpoint",
]

HoldContext = Annotated[
    RequestContext, Depends(require_permission(Permission.ADMIN_LEGAL_HOLD_MANAGE))
]


@router.post(
    "/admin/legal-holds",
    response_model=LegalHoldRead,
    status_code=status.HTTP_201_CREATED,
    tags=["admin"],
)
async def create_legal_hold_endpoint(
    payload: LegalHoldCreate, session: SessionDependency, context: HoldContext
) -> LegalHoldRead:
    return LegalHoldRead.model_validate(await create_hold(session, context, payload))


@router.get("/admin/legal-holds", response_model=list[LegalHoldRead], tags=["admin"])
async def list_legal_holds_endpoint(
    session: SessionDependency,
    context: HoldContext,
    active: Annotated[bool | None, Query()] = None,
) -> list[LegalHoldRead]:
    holds = await list_holds(session, context, active=active)
    return [LegalHoldRead.model_validate(hold) for hold in holds]


@router.post("/admin/legal-holds/{hold_id}/release", response_model=LegalHoldRead, tags=["admin"])
async def release_legal_hold_endpoint(
    hold_id: str, payload: LegalHoldRelease, session: SessionDependency, context: HoldContext
) -> LegalHoldRead:
    return LegalHoldRead.model_validate(await release_hold(session, context, hold_id, payload))
