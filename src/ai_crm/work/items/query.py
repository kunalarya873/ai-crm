from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import RequestContext
from ...models import WorkItem, utc_now
from ..domain import (
    validate_work_item_status,
    validate_work_item_type,
)

__all__ = [
    "list_work_items",
]


async def list_work_items(
    session: AsyncSession,
    context: RequestContext,
    *,
    limit: int,
    offset: int,
    item_type: str | None = None,
    item_status: str | None = None,
    assignee_id: str | None = None,
    owner_id: str | None = None,
    team_key: str | None = None,
    overdue: bool = False,
    unassigned: bool = False,
    include_archived: bool = False,
) -> list[WorkItem]:
    statement = select(WorkItem).where(WorkItem.tenant_id == context.tenant_id)
    if not include_archived:
        statement = statement.where(WorkItem.archived_at.is_(None))
    if item_type:
        validate_work_item_type(item_type)
        statement = statement.where(WorkItem.item_type == item_type)
    if item_status:
        validate_work_item_status(item_status)
        statement = statement.where(WorkItem.status == item_status)
    if assignee_id:
        statement = statement.where(WorkItem.assignee_id == assignee_id)
    if owner_id:
        statement = statement.where(WorkItem.owner_id == owner_id)
    if team_key:
        statement = statement.where(WorkItem.team_key == team_key)
    if unassigned:
        statement = statement.where(WorkItem.assignee_id.is_(None))
    if overdue:
        statement = statement.where(
            WorkItem.due_at.is_not(None),
            WorkItem.due_at < utc_now(),
            WorkItem.status.not_in({"completed", "cancelled"}),
        )
    result = await session.scalars(
        statement.order_by(WorkItem.priority.desc(), WorkItem.due_at, WorkItem.created_at)
        .offset(offset)
        .limit(limit)
    )
    return list(result)
