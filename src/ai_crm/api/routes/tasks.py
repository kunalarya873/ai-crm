from typing import Annotated

from fastapi import Header, Query, Response, status

from ...domain import NotFoundError
from ...schemas import TaskCreate, TaskRead, TaskUpdate
from ...services import create_task, get_task, list_tasks, update_task
from .base import SessionDependency, TaskCreateContext, TaskReadContext, TaskUpdateContext, router
from .helpers import parse_if_match, set_etag, trim_page

__all__ = [
    "create_task_endpoint", "get_task_endpoint", "list_tasks_endpoint", "update_task_endpoint",
]


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
    response: Response,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    cursor: str | None = None,
    task_status: str | None = Query(default=None, alias="status"),
    assignee_id: str | None = None,
    contact_id: str | None = None,
    opportunity_id: str | None = None,
    overdue: bool = False,
) -> list[TaskRead]:
    tasks = await list_tasks(
        session,
        context,
        limit + 1,
        offset,
        task_status=task_status,
        assignee_id=assignee_id,
        contact_id=contact_id,
        opportunity_id=opportunity_id,
        overdue=overdue,
        cursor=cursor,
    )
    tasks = trim_page(response, tasks, limit)
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
