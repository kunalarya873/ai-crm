from typing import Annotated

from fastapi import Header, Query, Response, status

from ...schemas import (
    WorkItemCreate,
    WorkItemRead,
    WorkItemTransitionRequest,
    WorkItemUpdate,
)
from ...work import (
    create_work_item,
    get_work_item,
    list_work_items,
    transition_work_item,
    update_work_item,
)
from ..routes import parse_if_match, set_etag
from .base import SessionDependency, WorkManageContext, WorkReadContext, router

__all__ = [
    "create_work_item_endpoint", "get_work_item_endpoint", "list_work_items_endpoint",
    "transition_work_item_endpoint", "update_work_item_endpoint",
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
