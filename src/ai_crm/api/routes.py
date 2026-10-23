from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.deps import RequestContext, require_permission
from ..config import settings
from ..db import check_database, get_session
from ..domain import NotFoundError
from ..permissions import Permission
from ..schemas import (
    ActivityCreate,
    ActivityRead,
    CompanyCreate,
    CompanyRead,
    CompanyUpdate,
    ContactCreate,
    ContactRead,
    ContactUpdate,
    HealthResponse,
    OpportunityCreate,
    OpportunityRead,
    OpportunityUpdate,
    TaskCreate,
    TaskRead,
    TaskUpdate,
    TimelineEntry,
)
from ..services import (
    create_activity,
    create_company,
    create_contact,
    create_opportunity,
    create_task,
    get_company_for_tenant,
    get_contact,
    get_opportunity,
    get_task,
    get_timeline,
    list_companies,
    list_contacts,
    list_opportunities,
    list_tasks,
    update_company,
    update_contact,
    update_opportunity,
    update_task,
)

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


def parse_if_match(value: str | None) -> int | None:
    if value is None:
        return None
    normalized = value.strip()
    if normalized.startswith("W/"):
        raise HTTPException(status_code=400, detail="If-Match must use a strong version value")
    normalized = normalized.strip('"')
    try:
        version = int(normalized)
    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail="If-Match must contain an integer version",
        ) from error
    if version < 1:
        raise HTTPException(
            status_code=400,
            detail="If-Match must contain a positive integer version",
        )
    return version


def set_etag(response: Response, version: int) -> None:
    response.headers["ETag"] = f'"{version}"'


@router.get("/health", response_model=HealthResponse, tags=["system"])
async def health() -> HealthResponse:
    return HealthResponse(status="ok", service=settings.app_name, version=settings.app_version)


@router.get("/readiness", tags=["system"])
async def readiness() -> dict[str, str]:
    try:
        await check_database()
    except SQLAlchemyError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is not ready",
        ) from error
    return {"status": "ready", "database": "ok"}


@router.post(
    "/contacts",
    response_model=ContactRead,
    status_code=status.HTTP_201_CREATED,
    tags=["contacts"],
)
async def create_contact_endpoint(
    payload: ContactCreate,
    response: Response,
    session: SessionDependency,
    context: ContactCreateContext,
) -> ContactRead:
    contact = await create_contact(session, context, payload)
    set_etag(response, contact.version)
    return ContactRead.model_validate(contact)


@router.get("/contacts", response_model=list[ContactRead], tags=["contacts"])
async def list_contacts_endpoint(
    session: SessionDependency,
    context: ContactReadContext,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    company_id: str | None = None,
    owner_id: str | None = None,
    contact_status: str | None = Query(default=None, alias="status"),
    query: str | None = Query(default=None, alias="q"),
    archived: bool = False,
) -> list[ContactRead]:
    contacts = await list_contacts(
        session,
        context,
        limit,
        offset,
        company_id=company_id,
        owner_id=owner_id,
        contact_status=contact_status,
        query=query,
        archived=archived,
    )
    return [ContactRead.model_validate(contact) for contact in contacts]


@router.get("/contacts/{contact_id}", response_model=ContactRead, tags=["contacts"])
async def get_contact_endpoint(
    contact_id: str,
    response: Response,
    session: SessionDependency,
    context: ContactReadContext,
) -> ContactRead:
    contact = await get_contact(session, context, contact_id)
    if contact is None:
        raise NotFoundError("Contact not found")
    set_etag(response, contact.version)
    return ContactRead.model_validate(contact)


@router.patch("/contacts/{contact_id}", response_model=ContactRead, tags=["contacts"])
async def update_contact_endpoint(
    contact_id: str,
    payload: ContactUpdate,
    response: Response,
    session: SessionDependency,
    context: ContactUpdateContext,
    if_match: Annotated[str | None, Header()] = None,
) -> ContactRead:
    contact = await update_contact(
        session,
        context,
        contact_id,
        payload,
        parse_if_match(if_match),
    )
    set_etag(response, contact.version)
    return ContactRead.model_validate(contact)


@router.post(
    "/companies",
    response_model=CompanyRead,
    status_code=status.HTTP_201_CREATED,
    tags=["companies"],
)
async def create_company_endpoint(
    payload: CompanyCreate,
    response: Response,
    session: SessionDependency,
    context: CompanyCreateContext,
) -> CompanyRead:
    company = await create_company(session, context, payload)
    set_etag(response, company.version)
    return CompanyRead.model_validate(company)


@router.get("/companies", response_model=list[CompanyRead], tags=["companies"])
async def list_companies_endpoint(
    session: SessionDependency,
    context: CompanyReadContext,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[CompanyRead]:
    companies = await list_companies(session, context, limit, offset)
    return [CompanyRead.model_validate(company) for company in companies]


@router.get("/companies/{company_id}", response_model=CompanyRead, tags=["companies"])
async def get_company_endpoint(
    company_id: str,
    response: Response,
    session: SessionDependency,
    context: CompanyReadContext,
) -> CompanyRead:
    company = await get_company_for_tenant(session, context, company_id)
    set_etag(response, company.version)
    return CompanyRead.model_validate(company)


@router.patch("/companies/{company_id}", response_model=CompanyRead, tags=["companies"])
async def update_company_endpoint(
    company_id: str,
    payload: CompanyUpdate,
    response: Response,
    session: SessionDependency,
    context: CompanyUpdateContext,
    if_match: Annotated[str | None, Header()] = None,
) -> CompanyRead:
    company = await update_company(
        session,
        context,
        company_id,
        payload,
        parse_if_match(if_match),
    )
    set_etag(response, company.version)
    return CompanyRead.model_validate(company)


@router.post(
    "/opportunities",
    response_model=OpportunityRead,
    status_code=status.HTTP_201_CREATED,
    tags=["opportunities"],
)
async def create_opportunity_endpoint(
    payload: OpportunityCreate,
    response: Response,
    session: SessionDependency,
    context: OpportunityCreateContext,
) -> OpportunityRead:
    opportunity = await create_opportunity(session, context, payload)
    set_etag(response, opportunity.version)
    return OpportunityRead.model_validate(opportunity)


@router.get("/opportunities", response_model=list[OpportunityRead], tags=["opportunities"])
async def list_opportunities_endpoint(
    session: SessionDependency,
    context: OpportunityReadContext,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    stage: str | None = None,
    owner_id: str | None = None,
    company_id: str | None = None,
    opportunity_status: str | None = Query(default=None, alias="status"),
) -> list[OpportunityRead]:
    opportunities = await list_opportunities(
        session,
        context,
        limit,
        offset,
        stage=stage,
        owner_id=owner_id,
        company_id=company_id,
        opportunity_status=opportunity_status,
    )
    return [OpportunityRead.model_validate(opportunity) for opportunity in opportunities]


@router.get(
    "/opportunities/{opportunity_id}",
    response_model=OpportunityRead,
    tags=["opportunities"],
)
async def get_opportunity_endpoint(
    opportunity_id: str,
    response: Response,
    session: SessionDependency,
    context: OpportunityReadContext,
) -> OpportunityRead:
    opportunity = await get_opportunity(session, context, opportunity_id)
    if opportunity is None:
        raise NotFoundError("Opportunity not found")
    set_etag(response, opportunity.version)
    return OpportunityRead.model_validate(opportunity)


@router.patch(
    "/opportunities/{opportunity_id}",
    response_model=OpportunityRead,
    tags=["opportunities"],
)
async def update_opportunity_endpoint(
    opportunity_id: str,
    payload: OpportunityUpdate,
    response: Response,
    session: SessionDependency,
    context: OpportunityUpdateContext,
    if_match: Annotated[str | None, Header()] = None,
) -> OpportunityRead:
    opportunity = await update_opportunity(
        session,
        context,
        opportunity_id,
        payload,
        parse_if_match(if_match),
    )
    set_etag(response, opportunity.version)
    return OpportunityRead.model_validate(opportunity)


@router.post(
    "/activities",
    response_model=ActivityRead,
    status_code=status.HTTP_201_CREATED,
    tags=["activities"],
)
async def create_activity_endpoint(
    payload: ActivityCreate,
    session: SessionDependency,
    context: ActivityCreateContext,
) -> ActivityRead:
    activity = await create_activity(session, context, payload)
    return ActivityRead.model_validate(activity)


@router.get(
    "/contacts/{contact_id}/timeline",
    response_model=list[TimelineEntry],
    tags=["timeline"],
)
async def contact_timeline_endpoint(
    contact_id: str,
    session: SessionDependency,
    context: ActivityReadContext,
) -> list[TimelineEntry]:
    timeline = await get_timeline(session, context, contact_id=contact_id)
    return [TimelineEntry.model_validate(item) for item in timeline]


@router.get(
    "/opportunities/{opportunity_id}/timeline",
    response_model=list[TimelineEntry],
    tags=["timeline"],
)
async def opportunity_timeline_endpoint(
    opportunity_id: str,
    session: SessionDependency,
    context: ActivityReadContext,
) -> list[TimelineEntry]:
    timeline = await get_timeline(session, context, opportunity_id=opportunity_id)
    return [TimelineEntry.model_validate(item) for item in timeline]


@router.post(
    "/tasks",
    response_model=TaskRead,
    status_code=status.HTTP_201_CREATED,
    tags=["tasks"],
)
async def create_task_endpoint(
    payload: TaskCreate,
    response: Response,
    session: SessionDependency,
    context: TaskCreateContext,
) -> TaskRead:
    task = await create_task(session, context, payload)
    set_etag(response, task.version)
    return TaskRead.model_validate(task)


@router.get("/tasks", response_model=list[TaskRead], tags=["tasks"])
async def list_tasks_endpoint(
    session: SessionDependency,
    context: TaskReadContext,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    task_status: str | None = Query(default=None, alias="status"),
    assignee_id: str | None = None,
    contact_id: str | None = None,
    opportunity_id: str | None = None,
    overdue: bool = False,
) -> list[TaskRead]:
    tasks = await list_tasks(
        session,
        context,
        limit,
        offset,
        task_status=task_status,
        assignee_id=assignee_id,
        contact_id=contact_id,
        opportunity_id=opportunity_id,
        overdue=overdue,
    )
    return [TaskRead.model_validate(task) for task in tasks]


@router.get("/tasks/{task_id}", response_model=TaskRead, tags=["tasks"])
async def get_task_endpoint(
    task_id: str,
    response: Response,
    session: SessionDependency,
    context: TaskReadContext,
) -> TaskRead:
    task = await get_task(session, context, task_id)
    if task is None:
        raise NotFoundError("Task not found")
    set_etag(response, task.version)
    return TaskRead.model_validate(task)


@router.patch("/tasks/{task_id}", response_model=TaskRead, tags=["tasks"])
async def update_task_endpoint(
    task_id: str,
    payload: TaskUpdate,
    response: Response,
    session: SessionDependency,
    context: TaskUpdateContext,
    if_match: Annotated[str | None, Header()] = None,
) -> TaskRead:
    task = await update_task(
        session,
        context,
        task_id,
        payload,
        parse_if_match(if_match),
    )
    set_etag(response, task.version)
    return TaskRead.model_validate(task)
