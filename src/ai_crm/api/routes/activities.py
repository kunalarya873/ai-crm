from fastapi import status

from ...schemas import ActivityCreate, ActivityRead, TimelineEntry
from ...services import create_activity, get_timeline
from .base import ActivityCreateContext, ActivityReadContext, SessionDependency, router

__all__ = [
    "contact_timeline_endpoint", "create_activity_endpoint", "opportunity_timeline_endpoint",
]


@router.post(
    "/activities",
    response_model=ActivityRead,
    status_code=status.HTTP_201_CREATED,
    tags=["activities"],
)
async def create_activity_endpoint(
    payload: ActivityCreate,
    session: SessionDependency,
    context: ActivityCreateContext,
) -> ActivityRead:
    activity = await create_activity(session, context, payload)
    return ActivityRead.model_validate(activity)


@router.get(
    "/contacts/{contact_id}/timeline",
    response_model=list[TimelineEntry],
    tags=["timeline"],
)
async def contact_timeline_endpoint(
    contact_id: str,
    session: SessionDependency,
    context: ActivityReadContext,
) -> list[TimelineEntry]:
    timeline = await get_timeline(session, context, contact_id=contact_id)
    return [TimelineEntry.model_validate(item) for item in timeline]


@router.get(
    "/opportunities/{opportunity_id}/timeline",
    response_model=list[TimelineEntry],
    tags=["timeline"],
)
async def opportunity_timeline_endpoint(
    opportunity_id: str,
    session: SessionDependency,
    context: ActivityReadContext,
) -> list[TimelineEntry]:
    timeline = await get_timeline(session, context, opportunity_id=opportunity_id)
    return [TimelineEntry.model_validate(item) for item in timeline]
