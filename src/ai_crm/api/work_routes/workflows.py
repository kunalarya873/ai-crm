from typing import Annotated

from fastapi import Header, Query, status

from ...schemas import (
    WorkflowAdvance,
    WorkflowRead,
    WorkflowStart,
)
from ...work import (
    advance_workflow,
    get_workflow,
    list_workflows,
    resume_workflow,
    start_workflow,
)
from ..routes import parse_if_match
from .base import SessionDependency, WorkflowsManageContext, WorkflowsReadContext, router

__all__ = [
    "advance_workflow_endpoint", "get_workflow_endpoint", "list_workflows_endpoint",
    "resume_workflow_endpoint", "start_workflow_endpoint",
]


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
