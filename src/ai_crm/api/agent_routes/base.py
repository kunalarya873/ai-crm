from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import RequestContext, require_permission
from ...db import get_session
from ...permissions import Permission

__all__ = [
    "ManageContext", "ReadContext", "RunContext", "SessionDependency", "router",
]


router = APIRouter()


SessionDependency = Annotated[AsyncSession, Depends(get_session)]


ReadContext = Annotated[RequestContext, Depends(require_permission(Permission.AGENTS_READ))]


RunContext = Annotated[RequestContext, Depends(require_permission(Permission.AGENTS_RUN))]


ManageContext = Annotated[RequestContext, Depends(require_permission(Permission.AGENTS_MANAGE))]
