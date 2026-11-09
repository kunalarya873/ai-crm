from typing import Annotated

from fastapi import Header, status

from ...schemas import (
    ReminderCreate,
    ReminderRead,
)
from ...work import (
    acknowledge_reminder,
    create_reminder,
    list_reminders,
)
from .base import SessionDependency, WorkManageContext, WorkReadContext, router

__all__ = [
    "acknowledge_reminder_endpoint", "create_reminder_endpoint", "list_reminders_endpoint",
]


@router.post(
    "/work-items/{work_item_id}/reminders",
    response_model=ReminderRead,
    status_code=status.HTTP_201_CREATED,
    tags=["work"],
)
async def create_reminder_endpoint(
    work_item_id: str,
    payload: ReminderCreate,
    session: SessionDependency,
    context: WorkManageContext,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ReminderRead:
    reminder = await create_reminder(
        session,
        context,
        work_item_id,
        payload,
        idempotency_key or "",
    )
    return ReminderRead.model_validate(reminder)


@router.get(
    "/work-items/{work_item_id}/reminders",
    response_model=list[ReminderRead],
    tags=["work"],
)
async def list_reminders_endpoint(
    work_item_id: str,
    session: SessionDependency,
    context: WorkReadContext,
) -> list[ReminderRead]:
    reminders = await list_reminders(session, context, work_item_id)
    return [ReminderRead.model_validate(reminder) for reminder in reminders]


@router.post(
    "/reminders/{reminder_id}/acknowledge",
    response_model=ReminderRead,
    tags=["work"],
)
async def acknowledge_reminder_endpoint(
    reminder_id: str,
    session: SessionDependency,
    context: WorkManageContext,
) -> ReminderRead:
    reminder = await acknowledge_reminder(session, context, reminder_id)
    return ReminderRead.model_validate(reminder)
