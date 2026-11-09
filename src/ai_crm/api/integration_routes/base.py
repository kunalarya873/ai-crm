from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import RequestContext, require_permission
from ...db import get_session
from ...permissions import Permission

__all__ = [
    "ManageContext", "ReadContext", "SessionDependency", "SyncContext", "WriteContext", "router",
]


router = APIRouter()


SessionDependency = Annotated[AsyncSession, Depends(get_session)]


ReadContext = Annotated[
    RequestContext,
    Depends(require_permission(Permission.INTEGRATIONS_READ)),
]


ManageContext = Annotated[
    RequestContext,
    Depends(require_permission(Permission.INTEGRATIONS_MANAGE)),
]


SyncContext = Annotated[
    RequestContext,
    Depends(require_permission(Permission.INTEGRATIONS_SYNC)),
]


WriteContext = Annotated[
    RequestContext,
    Depends(require_permission(Permission.INTEGRATIONS_WRITE)),
]
