from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import RequestContext
from ...audit import record_audit, record_outbox_event
from ...models import WorkItem
from ...schemas import WorkItemCreate
from ..domain import require_aware_datetime, validate_timezone, validate_work_item_type
from .refs import _validate_references

__all__ = [
    "create_work_item", "create_work_item_in_session",
]


async def create_work_item_in_session(
    session: AsyncSession,
    context: RequestContext,
    payload: WorkItemCreate,
) -> WorkItem:
    """Create a work item without committing, so callers can make it atomic with theirs."""
    validate_work_item_type(payload.item_type)
    validate_timezone(payload.timezone)
    require_aware_datetime(payload.due_at, "due_at")
    await _validate_references(
        session,
        context,
        contact_id=payload.contact_id,
        opportunity_id=payload.opportunity_id,
        dependency_ids=payload.depends_on_ids,
    )
    item = WorkItem(
        tenant_id=context.tenant_id,
        created_by=context.actor_id,
        **payload.model_dump(),
    )
    session.add(item)
    await session.flush()
    await record_audit(
        session,
        context,
        "work_item.created",
        "work_item",
        item.id,
        details={"item_type": item.item_type, "status": item.status},
    )
    await record_outbox_event(
        session,
        context,
        "work_item.created",
        "work_item",
        item.id,
        {"item_type": item.item_type, "status": item.status},
    )
    return item


async def create_work_item(
    session: AsyncSession,
    context: RequestContext,
    payload: WorkItemCreate,
) -> WorkItem:
    item = await create_work_item_in_session(session, context, payload)
    await session.commit()
    await session.refresh(item)
    return item
