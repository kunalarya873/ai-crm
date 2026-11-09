from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.deps import RequestContext
from ..domain import ConflictError
from ..models import Activity
from ..schemas import ActivityCreate
from .common import utc_now
from .events import _record_create_events
from .lookups import _validate_relationships

__all__ = [
    "create_activity", "get_activity",
]


async def create_activity(
    session: AsyncSession,
    context: RequestContext,
    payload: ActivityCreate,
) -> Activity:
    await _validate_relationships(
        session,
        context,
        company_id=payload.company_id,
        contact_id=payload.contact_id,
        opportunity_id=payload.opportunity_id,
    )
    if payload.source_system and payload.source_record_id:
        duplicate = await session.scalar(
            select(Activity).where(
                Activity.tenant_id == context.tenant_id,
                Activity.source_system == payload.source_system,
                Activity.source_record_id == payload.source_record_id,
            )
        )
        if duplicate is not None:
            raise ConflictError("An activity with this source record already exists")
    values = payload.model_dump()
    values["event_at"] = values["event_at"] or utc_now()
    activity = Activity(
        tenant_id=context.tenant_id,
        actor_id=context.actor_id,
        **values,
    )
    session.add(activity)
    await session.flush()
    await _record_create_events(
        session,
        context,
        action="activity.created",
        entity_type="activity",
        entity_id=activity.id,
        version=None,
    )
    await session.commit()
    await session.refresh(activity)
    return activity


async def get_activity(
    session: AsyncSession,
    context: RequestContext,
    activity_id: str,
) -> Activity | None:
    return await session.scalar(
        select(Activity).where(
            Activity.id == activity_id,
            Activity.tenant_id == context.tenant_id,
        )
    )
