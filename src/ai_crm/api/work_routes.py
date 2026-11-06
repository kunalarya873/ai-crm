from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.deps import RequestContext, require_permission
from ..db import get_session
from ..permissions import Permission
from ..schemas import (
    JobClaimRequest,
    JobCompleteRequest,
    JobCreate,
    JobFailureRequest,
    JobRead,
    ReminderCreate,
    ReminderRead,
    WorkflowAdvance,
    WorkflowRead,
    WorkflowStart,
    WorkItemCreate,
    WorkItemRead,
    WorkItemTransitionRequest,
    WorkItemUpdate,
)
from ..work import (
    acknowledge_reminder,
    advance_workflow,
    cancel_job,
    claim_next_job,
    complete_job,
    create_job,
    create_reminder,
    create_work_item,
    fail_job,
    get_job,
    get_work_item,
    get_workflow,
    heartbeat_job,
    list_jobs,
    list_reminders,
    list_work_items,
    list_workflows,
    reconcile_expired_jobs,
    resume_workflow,
    retry_job,
    start_workflow,
    transition_work_item,
    update_work_item,
)
from .routes import parse_if_match, set_etag

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


@router.post(
    "/work-items",
    response_model=WorkItemRead,
    status_code=status.HTTP_201_CREATED,
    tags=["work"],
)
async def create_work_item_endpoint(
    payload: WorkItemCreate,
    response: Response,
    session: SessionDependency,
    context: WorkManageContext,
) -> WorkItemRead:
    item = await create_work_item(session, context, payload)
    set_etag(response, item.version)
    return WorkItemRead.model_validate(item)


@router.get("/work-items", response_model=list[WorkItemRead], tags=["work"])
async def list_work_items_endpoint(
    session: SessionDependency,
    context: WorkReadContext,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    item_type: str | None = None,
    item_status: str | None = Query(default=None, alias="status"),
    assignee_id: str | None = None,
    owner_id: str | None = None,
    team_key: str | None = None,
    overdue: bool = False,
    unassigned: bool = False,
    include_archived: bool = False,
) -> list[WorkItemRead]:
    items = await list_work_items(
        session,
        context,
        limit=limit,
        offset=offset,
        item_type=item_type,
        item_status=item_status,
        assignee_id=assignee_id,
        owner_id=owner_id,
        team_key=team_key,
        overdue=overdue,
        unassigned=unassigned,
        include_archived=include_archived,
    )
    return [WorkItemRead.model_validate(item) for item in items]


@router.get("/work-items/{work_item_id}", response_model=WorkItemRead, tags=["work"])
async def get_work_item_endpoint(
    work_item_id: str,
    response: Response,
    session: SessionDependency,
    context: WorkReadContext,
) -> WorkItemRead:
    item = await get_work_item(session, context, work_item_id)
    set_etag(response, item.version)
    return WorkItemRead.model_validate(item)


@router.patch("/work-items/{work_item_id}", response_model=WorkItemRead, tags=["work"])
async def update_work_item_endpoint(
    work_item_id: str,
    payload: WorkItemUpdate,
    response: Response,
    session: SessionDependency,
    context: WorkManageContext,
    if_match: Annotated[str | None, Header()] = None,
) -> WorkItemRead:
    item = await update_work_item(
        session,
        context,
        work_item_id,
        payload,
        parse_if_match(if_match),
    )
    set_etag(response, item.version)
    return WorkItemRead.model_validate(item)


@router.post(
    "/work-items/{work_item_id}/transition",
    response_model=WorkItemRead,
    tags=["work"],
)
async def transition_work_item_endpoint(
    work_item_id: str,
    payload: WorkItemTransitionRequest,
    response: Response,
    session: SessionDependency,
    context: WorkManageContext,
    if_match: Annotated[str | None, Header()] = None,
) -> WorkItemRead:
    item = await transition_work_item(
        session,
        context,
        work_item_id,
        payload,
        parse_if_match(if_match),
    )
    set_etag(response, item.version)
    return WorkItemRead.model_validate(item)


@router.post(
    "/work-items/{work_item_id}/reminders",
    response_model=ReminderRead,
    status_code=status.HTTP_201_CREATED,
    tags=["work"],
)
async def create_reminder_endpoint(
    work_item_id: str,
    payload: ReminderCreate,
    session: SessionDependency,
    context: WorkManageContext,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ReminderRead:
    reminder = await create_reminder(
        session,
        context,
        work_item_id,
        payload,
        idempotency_key or "",
    )
    return ReminderRead.model_validate(reminder)


@router.get(
    "/work-items/{work_item_id}/reminders",
    response_model=list[ReminderRead],
    tags=["work"],
)
async def list_reminders_endpoint(
    work_item_id: str,
    session: SessionDependency,
    context: WorkReadContext,
) -> list[ReminderRead]:
    reminders = await list_reminders(session, context, work_item_id)
    return [ReminderRead.model_validate(reminder) for reminder in reminders]


@router.post(
    "/reminders/{reminder_id}/acknowledge",
    response_model=ReminderRead,
    tags=["work"],
)
async def acknowledge_reminder_endpoint(
    reminder_id: str,
    session: SessionDependency,
    context: WorkManageContext,
) -> ReminderRead:
    reminder = await acknowledge_reminder(session, context, reminder_id)
    return ReminderRead.model_validate(reminder)


@router.post(
    "/jobs",
    response_model=JobRead,
    status_code=status.HTTP_201_CREATED,
    tags=["jobs"],
)
async def create_job_endpoint(
    payload: JobCreate,
    session: SessionDependency,
    context: JobsManageContext,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JobRead:
    job = await create_job(session, context, payload, idempotency_key or "")
    return JobRead.model_validate(job)


@router.get("/jobs", response_model=list[JobRead], tags=["jobs"])
async def list_jobs_endpoint(
    session: SessionDependency,
    context: JobsReadContext,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    queue: str | None = None,
    job_status: str | None = Query(default=None, alias="status"),
) -> list[JobRead]:
    jobs = await list_jobs(
        session,
        context,
        limit=limit,
        offset=offset,
        queue=queue,
        job_status=job_status,
    )
    return [JobRead.model_validate(job) for job in jobs]


@router.post("/jobs/reconcile-expired", response_model=list[JobRead], tags=["jobs"])
async def reconcile_expired_jobs_endpoint(
    session: SessionDependency,
    context: JobsManageContext,
) -> list[JobRead]:
    jobs = await reconcile_expired_jobs(session, context)
    return [JobRead.model_validate(job) for job in jobs]


@router.post("/jobs/claim-next", response_model=JobRead | None, tags=["jobs"])
async def claim_next_job_endpoint(
    payload: JobClaimRequest,
    session: SessionDependency,
    context: JobsManageContext,
    queue: str = "default",
) -> JobRead | None:
    job = await claim_next_job(
        session,
        context,
        queue=queue,
        worker_id=payload.worker_id,
        lease_seconds=payload.lease_seconds,
    )
    return JobRead.model_validate(job) if job else None


@router.get("/jobs/{job_id}", response_model=JobRead, tags=["jobs"])
async def get_job_endpoint(
    job_id: str,
    session: SessionDependency,
    context: JobsReadContext,
) -> JobRead:
    return JobRead.model_validate(await get_job(session, context, job_id))


@router.post("/jobs/{job_id}/heartbeat", response_model=JobRead, tags=["jobs"])
async def heartbeat_job_endpoint(
    job_id: str,
    payload: JobClaimRequest,
    session: SessionDependency,
    context: JobsManageContext,
) -> JobRead:
    job = await heartbeat_job(
        session,
        context,
        job_id,
        payload.worker_id,
        payload.lease_seconds,
    )
    return JobRead.model_validate(job)


@router.post("/jobs/{job_id}/complete", response_model=JobRead, tags=["jobs"])
async def complete_job_endpoint(
    job_id: str,
    payload: JobCompleteRequest,
    session: SessionDependency,
    context: JobsManageContext,
    worker_id: Annotated[str | None, Header(alias="X-Worker-ID")] = None,
) -> JobRead:
    job = await complete_job(session, context, job_id, worker_id or "", payload.result)
    return JobRead.model_validate(job)


@router.post("/jobs/{job_id}/fail", response_model=JobRead, tags=["jobs"])
async def fail_job_endpoint(
    job_id: str,
    payload: JobFailureRequest,
    session: SessionDependency,
    context: JobsManageContext,
    worker_id: Annotated[str | None, Header(alias="X-Worker-ID")] = None,
) -> JobRead:
    job = await fail_job(session, context, job_id, worker_id or "", payload)
    return JobRead.model_validate(job)


@router.post("/jobs/{job_id}/retry", response_model=JobRead, tags=["jobs"])
async def retry_job_endpoint(
    job_id: str,
    session: SessionDependency,
    context: JobsManageContext,
) -> JobRead:
    return JobRead.model_validate(await retry_job(session, context, job_id))


@router.post("/jobs/{job_id}/cancel", response_model=JobRead, tags=["jobs"])
async def cancel_job_endpoint(
    job_id: str,
    session: SessionDependency,
    context: JobsManageContext,
) -> JobRead:
    return JobRead.model_validate(await cancel_job(session, context, job_id))


@router.post(
    "/workflows",
    response_model=WorkflowRead,
    status_code=status.HTTP_201_CREATED,
    tags=["workflows"],
)
async def start_workflow_endpoint(
    payload: WorkflowStart,
    session: SessionDependency,
    context: WorkflowsManageContext,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> WorkflowRead:
    workflow = await start_workflow(session, context, payload, idempotency_key or "")
    return WorkflowRead.model_validate(workflow)


@router.get("/workflows", response_model=list[WorkflowRead], tags=["workflows"])
async def list_workflows_endpoint(
    session: SessionDependency,
    context: WorkflowsReadContext,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    workflow_status: str | None = Query(default=None, alias="status"),
    owner_id: str | None = None,
) -> list[WorkflowRead]:
    workflows = await list_workflows(
        session,
        context,
        limit=limit,
        offset=offset,
        workflow_status=workflow_status,
        owner_id=owner_id,
    )
    return [WorkflowRead.model_validate(workflow) for workflow in workflows]


@router.get("/workflows/{workflow_id}", response_model=WorkflowRead, tags=["workflows"])
async def get_workflow_endpoint(
    workflow_id: str,
    session: SessionDependency,
    context: WorkflowsReadContext,
) -> WorkflowRead:
    return WorkflowRead.model_validate(await get_workflow(session, context, workflow_id))


@router.post("/workflows/{workflow_id}/advance", response_model=WorkflowRead, tags=["workflows"])
async def advance_workflow_endpoint(
    workflow_id: str,
    payload: WorkflowAdvance,
    session: SessionDependency,
    context: WorkflowsManageContext,
    if_match: Annotated[str | None, Header()] = None,
) -> WorkflowRead:
    workflow = await advance_workflow(
        session,
        context,
        workflow_id,
        payload,
        parse_if_match(if_match),
    )
    return WorkflowRead.model_validate(workflow)


@router.post("/workflows/{workflow_id}/resume", response_model=WorkflowRead, tags=["workflows"])
async def resume_workflow_endpoint(
    workflow_id: str,
    session: SessionDependency,
    context: WorkflowsManageContext,
    if_match: Annotated[str | None, Header()] = None,
) -> WorkflowRead:
    workflow = await resume_workflow(
        session,
        context,
        workflow_id,
        parse_if_match(if_match),
    )
    return WorkflowRead.model_validate(workflow)
