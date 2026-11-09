from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import RequestContext, require_permission
from ...db import get_session
from ...permissions import Permission

__all__ = [
    "ApproveContext", "ExecuteContext", "ProposeContext", "ReadContext", "RecoverContext",
    "SessionDependency", "router",
]


router = APIRouter()


SessionDependency = Annotated[AsyncSession, Depends(get_session)]


ReadContext = Annotated[
    RequestContext,
    Depends(require_permission(Permission.ACTIONS_READ)),
]


ProposeContext = Annotated[
    RequestContext,
    Depends(require_permission(Permission.ACTIONS_PROPOSE)),
]


ApproveContext = Annotated[
    RequestContext,
    Depends(require_permission(Permission.ACTIONS_APPROVE)),
]


ExecuteContext = Annotated[
    RequestContext,
    Depends(require_permission(Permission.ACTIONS_EXECUTE)),
]


RecoverContext = Annotated[
    RequestContext,
    Depends(require_permission(Permission.ACTIONS_RECOVER)),
]
