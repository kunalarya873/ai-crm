from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.deps import RequestContext
from ..domain import (
    ALLOWED_TASK_TRANSITIONS,
    InvalidRequestError,
    NotFoundError,
    VersionConflictError,
    validate_transition,
)
from ..models import Task
from ..schemas import TaskUpdate
from .common import require_version, utc_now
from .events import _record_update_events
from .lookups import _validate_relationships

__all__ = [
    "update_task",
]


async def update_task(
    session: AsyncSession,
    context: RequestContext,
    task_id: str,
    payload: TaskUpdate,
    expected_version: int | None,
) -> Task:
    expected = require_version(expected_version)
    task = await session.scalar(
        select(Task).where(Task.id == task_id, Task.tenant_id == context.tenant_id)
    )
    if task is None:
        raise NotFoundError("Task not found")
    if task.version != expected:
        raise VersionConflictError("record_version_conflict")
    changes = payload.model_dump(exclude_unset=True)
    archived = changes.pop("archived", None)
    if not changes and archived is None:
        raise InvalidRequestError("At least one field is required")
    await _validate_relationships(
        session,
        context,
        contact_id=changes.get("contact_id", task.contact_id),
        opportunity_id=changes.get("opportunity_id", task.opportunity_id),
    )
    if "status" in changes:
        validate_transition(task.status, changes["status"], ALLOWED_TASK_TRANSITIONS)
        if changes["status"] == "completed":
            changes["completed_at"] = utc_now()
    if archived is not None:
        changes["archived_at"] = utc_now() if archived else None
    old_state = {key: getattr(task, key) for key in changes if hasattr(task, key)}
    changes.update(version=expected + 1, updated_at=utc_now())
    result = cast(
        CursorResult[Any],
        await session.execute(
            update(Task)
            .where(
                Task.id == task_id,
                Task.tenant_id == context.tenant_id,
                Task.version == expected,
            )
            .values(**changes)
        ),
    )
    if result.rowcount != 1:
        await session.rollback()
        raise VersionConflictError("record_version_conflict")
    await _record_update_events(
        session,
        context,
        action="task.updated",
        entity_type="task",
        entity_id=task_id,
        old_state=old_state,
        new_state=changes,
        version=expected + 1,
    )
    await session.commit()
    await session.refresh(task)
    return task
