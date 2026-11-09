from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.deps import RequestContext
from ..domain import (
    ALLOWED_TASK_TRANSITIONS,
    InvalidRequestError,
)
from ..models import Task
from ..pagination import page_statement
from ..schemas import (
    TaskCreate,
)
from .common import utc_now
from .events import _record_create_events
from .lookups import _validate_relationships

__all__ = [
    "create_task", "get_task", "list_tasks",
]


async def create_task(
    session: AsyncSession,
    context: RequestContext,
    payload: TaskCreate,
) -> Task:
    if payload.status not in ALLOWED_TASK_TRANSITIONS:
        raise InvalidRequestError("Invalid task status")
    await _validate_relationships(
        session,
        context,
        contact_id=payload.contact_id,
        opportunity_id=payload.opportunity_id,
    )
    values = payload.model_dump()
    completed_at = utc_now() if values["status"] == "completed" else None
    task = Task(tenant_id=context.tenant_id, completed_at=completed_at, **values)
    session.add(task)
    await session.flush()
    await _record_create_events(
        session,
        context,
        action="task.created",
        entity_type="task",
        entity_id=task.id,
        version=task.version,
    )
    await session.commit()
    await session.refresh(task)
    return task


async def list_tasks(
    session: AsyncSession,
    context: RequestContext,
    limit: int,
    offset: int,
    *,
    task_status: str | None = None,
    assignee_id: str | None = None,
    contact_id: str | None = None,
    opportunity_id: str | None = None,
    overdue: bool = False,
    cursor: str | None = None,
) -> Sequence[Task]:
    statement = select(Task).where(
        Task.tenant_id == context.tenant_id,
        Task.archived_at.is_(None),
    )
    if task_status:
        statement = statement.where(Task.status == task_status)
    if assignee_id:
        statement = statement.where(Task.assignee_id == assignee_id)
    if contact_id:
        statement = statement.where(Task.contact_id == contact_id)
    if opportunity_id:
        statement = statement.where(Task.opportunity_id == opportunity_id)
    if overdue:
        statement = statement.where(
            Task.due_at < utc_now(),
            Task.status.notin_(["completed", "cancelled"]),
        )
    result = await session.scalars(page_statement(statement, Task, limit, offset, cursor))
    return result.all()


async def get_task(
    session: AsyncSession,
    context: RequestContext,
    task_id: str,
) -> Task | None:
    return await session.scalar(
        select(Task).where(Task.id == task_id, Task.tenant_id == context.tenant_id)
    )
