from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import RequestContext, require_permission
from ...db import get_session
from ...permissions import Permission

__all__ = [
    "ActivityCreateContext", "ActivityReadContext", "CompanyCreateContext", "CompanyReadContext",
    "CompanyUpdateContext", "ContactCreateContext", "ContactReadContext", "ContactUpdateContext",
    "OpportunityCreateContext", "OpportunityReadContext", "OpportunityUpdateContext",
    "SessionDependency", "TaskCreateContext", "TaskReadContext", "TaskUpdateContext", "router",
]


router = APIRouter()


SessionDependency = Annotated[AsyncSession, Depends(get_session)]


ContactReadContext = Annotated[
    RequestContext,
    Depends(require_permission(Permission.CONTACTS_READ)),
]


ContactCreateContext = Annotated[
    RequestContext,
    Depends(require_permission(Permission.CONTACTS_CREATE)),
]


ContactUpdateContext = Annotated[
    RequestContext,
    Depends(require_permission(Permission.CONTACTS_UPDATE)),
]


CompanyReadContext = Annotated[
    RequestContext,
    Depends(require_permission(Permission.COMPANIES_READ)),
]


CompanyCreateContext = Annotated[
    RequestContext,
    Depends(require_permission(Permission.COMPANIES_CREATE)),
]


CompanyUpdateContext = Annotated[
    RequestContext,
    Depends(require_permission(Permission.COMPANIES_UPDATE)),
]


OpportunityReadContext = Annotated[
    RequestContext,
    Depends(require_permission(Permission.OPPORTUNITIES_READ)),
]


OpportunityCreateContext = Annotated[
    RequestContext,
    Depends(require_permission(Permission.OPPORTUNITIES_CREATE)),
]


OpportunityUpdateContext = Annotated[
    RequestContext,
    Depends(require_permission(Permission.OPPORTUNITIES_UPDATE)),
]


ActivityReadContext = Annotated[
    RequestContext,
    Depends(require_permission(Permission.ACTIVITIES_READ)),
]


ActivityCreateContext = Annotated[
    RequestContext,
    Depends(require_permission(Permission.ACTIVITIES_CREATE)),
]


TaskReadContext = Annotated[
    RequestContext,
    Depends(require_permission(Permission.TASKS_READ)),
]


TaskCreateContext = Annotated[
    RequestContext,
    Depends(require_permission(Permission.TASKS_CREATE)),
]


TaskUpdateContext = Annotated[
    RequestContext,
    Depends(require_permission(Permission.TASKS_UPDATE)),
]
