from typing import Annotated

from fastapi import Depends, Header, Response

from ...api.deps import RequestContext, require_permission
from ...flags import effective_flags, set_flag
from ...permissions import Permission
from ...schemas import FeatureFlagRead, FeatureFlagUpdate
from ..routes import parse_if_match, set_etag
from .base import SessionDependency, router

__all__ = [
    "FlagsManageContext", "FlagsReadContext", "list_feature_flags_endpoint",
    "set_feature_flag_endpoint",
]


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
