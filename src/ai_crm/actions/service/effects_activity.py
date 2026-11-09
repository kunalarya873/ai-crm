from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import RequestContext
from ...audit import record_audit, record_outbox_event
from ...models import Activity, WorkItem, utc_now
from ...schemas import ActivityCreate
from ..registry import ApprovalRequestAction
from .effects_tasks import _validate_relationships

__all__ = [
    "_create_activity", "_create_approval_work_item",
]


async def _create_activity(
    session: AsyncSession,
    context: RequestContext,
    payload: BaseModel,
) -> dict[str, object]:
    activity_payload = ActivityCreate.model_validate(payload.model_dump(exclude_unset=True))
    await _validate_relationships(
        session,
        context,
        contact_id=activity_payload.contact_id,
        company_id=activity_payload.company_id,
        opportunity_id=activity_payload.opportunity_id,
    )
    values = activity_payload.model_dump()
    values["event_at"] = values["event_at"] or utc_now()
    activity = Activity(tenant_id=context.tenant_id, actor_id=context.actor_id, **values)
    session.add(activity)
    await session.flush()
    await record_audit(
        session,
        context,
        "activity.created",
        "activity",
        activity.id,
        details={"via": "action_execution"},
    )
    await record_outbox_event(
        session,
        context,
        "activity.created",
        "activity",
        activity.id,
        {"via": "action_execution"},
    )
    return {"entity_type": "activity", "entity_id": activity.id}


async def _create_approval_work_item(
    session: AsyncSession,
    context: RequestContext,
    payload: BaseModel,
) -> dict[str, object]:
    action = ApprovalRequestAction.model_validate(payload.model_dump())
    work_item = WorkItem(
        tenant_id=context.tenant_id,
        item_type="approval",
        title=action.title,
        description=action.description,
        status="open",
        priority=50,
        owner_id=context.actor_id,
        assignee_id=action.assignee_id,
        due_at=action.due_at,
        source=action.source,
        created_by=context.actor_id,
    )
    session.add(work_item)
    await session.flush()
    await record_audit(
        session,
        context,
        "work_item.created",
        "work_item",
        work_item.id,
        details={"item_type": "approval", "via": "action_execution"},
    )
    await record_outbox_event(
        session,
        context,
        "work_item.created",
        "work_item",
        work_item.id,
        {"item_type": "approval", "via": "action_execution"},
    )
    return {"entity_type": "work_item", "entity_id": work_item.id, "item_type": "approval"}
