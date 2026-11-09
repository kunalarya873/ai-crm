from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import RequestContext, require_permission
from ...db import get_session
from ...permissions import Permission

__all__ = [
    "ContextContext", "ManageContext", "ReadContext", "SessionDependency", "router",
]


router = APIRouter()


SessionDependency = Annotated[AsyncSession, Depends(get_session)]


ReadContext = Annotated[
    RequestContext,
    Depends(require_permission(Permission.KNOWLEDGE_READ)),
]


ManageContext = Annotated[
    RequestContext,
    Depends(require_permission(Permission.KNOWLEDGE_MANAGE)),
]


ContextContext = Annotated[
    RequestContext,
    Depends(require_permission(Permission.KNOWLEDGE_CONTEXT)),
]
