from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import RequestContext, require_permission
from ...db import get_session
from ...permissions import Permission

__all__ = [
    "JobsManageContext", "JobsReadContext", "SessionDependency", "WorkManageContext",
    "WorkReadContext", "WorkflowsManageContext", "WorkflowsReadContext", "router",
]


router = APIRouter()


SessionDependency = Annotated[AsyncSession, Depends(get_session)]


WorkReadContext = Annotated[
    RequestContext,
    Depends(require_permission(Permission.WORK_READ)),
]


WorkManageContext = Annotated[
    RequestContext,
    Depends(require_permission(Permission.WORK_MANAGE)),
]


JobsReadContext = Annotated[
    RequestContext,
    Depends(require_permission(Permission.JOBS_READ)),
]


JobsManageContext = Annotated[
    RequestContext,
    Depends(require_permission(Permission.JOBS_MANAGE)),
]


WorkflowsReadContext = Annotated[
    RequestContext,
    Depends(require_permission(Permission.WORKFLOWS_READ)),
]


WorkflowsManageContext = Annotated[
    RequestContext,
    Depends(require_permission(Permission.WORKFLOWS_MANAGE)),
]
