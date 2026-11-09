from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.deps import RequestContext
from ..domain import InvalidRequestError
from ..models import Activity, Task
from .lookups import get_contact_for_tenant, get_opportunity_for_tenant

__all__ = [
    "get_timeline",
]


async def get_timeline(
    session: AsyncSession,
    context: RequestContext,
    *,
    contact_id: str | None = None,
    opportunity_id: str | None = None,
) -> list[dict[str, object]]:
    if contact_id:
        await get_contact_for_tenant(session, context, contact_id)
        activities = list(
            await session.scalars(
                select(Activity).where(
                    Activity.tenant_id == context.tenant_id,
                    Activity.contact_id == contact_id,
                )
            )
        )
        tasks = list(
            await session.scalars(
                select(Task).where(
                    Task.tenant_id == context.tenant_id,
                    Task.contact_id == contact_id,
                    Task.archived_at.is_(None),
                )
            )
        )
    elif opportunity_id:
        await get_opportunity_for_tenant(session, context, opportunity_id)
        activities = list(
            await session.scalars(
                select(Activity).where(
                    Activity.tenant_id == context.tenant_id,
                    Activity.opportunity_id == opportunity_id,
                )
            )
        )
        tasks = list(
            await session.scalars(
                select(Task).where(
                    Task.tenant_id == context.tenant_id,
                    Task.opportunity_id == opportunity_id,
                    Task.archived_at.is_(None),
                )
            )
        )
    else:
        raise InvalidRequestError("A contact_id or opportunity_id is required")

    timeline = [
        {
            "id": activity.id,
            "type": "activity",
            "title": activity.subject,
            "body": activity.body,
            "occurred_at": activity.event_at,
            "status": None,
            "actor_id": activity.actor_id,
            "source": activity.source_system,
        }
        for activity in activities
    ]
    timeline.extend(
        {
            "id": task.id,
            "type": "task",
            "title": task.title,
            "body": task.description,
            "occurred_at": task.created_at,
            "status": task.status,
            "actor_id": task.assignee_id,
            "source": task.source,
        }
        for task in tasks
    )
    timeline.sort(key=lambda item: (item["occurred_at"], item["id"]), reverse=True)
    return timeline
