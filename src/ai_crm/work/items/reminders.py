from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import RequestContext
from ...audit import record_audit
from ...domain import ConflictError, InvalidRequestError, NotFoundError
from ...models import ReminderDelivery, utc_now
from ...schemas import ReminderCreate
from ..domain import (
    require_aware_datetime,
    validate_timezone,
)
from ..jobs import create_job_in_session
from .refs import _same_instant, get_work_item

__all__ = [
    "acknowledge_reminder", "create_reminder", "list_reminders",
]


async def create_reminder(
    session: AsyncSession,
    context: RequestContext,
    work_item_id: str,
    payload: ReminderCreate,
    idempotency_key: str,
) -> ReminderDelivery:
    if not idempotency_key.strip():
        raise InvalidRequestError("Idempotency-Key header is required")
    item = await get_work_item(session, context, work_item_id)
    require_aware_datetime(payload.scheduled_for, "scheduled_for")
    timezone = validate_timezone(payload.timezone)
    existing = await session.scalar(
        select(ReminderDelivery).where(
            ReminderDelivery.tenant_id == context.tenant_id,
            ReminderDelivery.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if (
            existing.work_item_id != item.id
            or existing.reminder_kind != payload.reminder_kind
            or not _same_instant(existing.scheduled_for, payload.scheduled_for)
        ):
            raise ConflictError("Idempotency-Key was reused for a different reminder")
        return existing
    reminder = ReminderDelivery(
        tenant_id=context.tenant_id,
        work_item_id=item.id,
        reminder_kind=payload.reminder_kind,
        scheduled_for=payload.scheduled_for,
        timezone=timezone,
        idempotency_key=idempotency_key,
    )
    session.add(reminder)
    await session.flush()
    await create_job_in_session(
        session,
        context,
        idempotency_key=f"reminder:{reminder.id}",
        job_type="reminder.dispatch",
        queue="reminders",
        payload={"reminder_id": reminder.id, "work_item_id": item.id},
        run_at=payload.scheduled_for,
        max_attempts=3,
        backoff_seconds=30,
        timeout_seconds=300,
    )
    await record_audit(
        session,
        context,
        "reminder.scheduled",
        "reminder_delivery",
        reminder.id,
        details={"work_item_id": item.id, "scheduled_for": payload.scheduled_for.isoformat()},
    )
    await session.commit()
    await session.refresh(reminder)
    return reminder


async def list_reminders(
    session: AsyncSession,
    context: RequestContext,
    work_item_id: str,
) -> list[ReminderDelivery]:
    await get_work_item(session, context, work_item_id)
    result = await session.scalars(
        select(ReminderDelivery)
        .where(
            ReminderDelivery.tenant_id == context.tenant_id,
            ReminderDelivery.work_item_id == work_item_id,
        )
        .order_by(ReminderDelivery.scheduled_for)
    )
    return list(result)


async def acknowledge_reminder(
    session: AsyncSession,
    context: RequestContext,
    reminder_id: str,
) -> ReminderDelivery:
    reminder = await session.scalar(
        select(ReminderDelivery).where(
            ReminderDelivery.id == reminder_id,
            ReminderDelivery.tenant_id == context.tenant_id,
        )
    )
    if reminder is None:
        raise NotFoundError("Reminder not found")
    if reminder.status == "cancelled":
        raise ConflictError("Cancelled reminders cannot be acknowledged")
    reminder.status = "acknowledged"
    reminder.acknowledged_at = utc_now()
    await record_audit(
        session,
        context,
        "reminder.acknowledged",
        "reminder_delivery",
        reminder.id,
    )
    await session.commit()
    await session.refresh(reminder)
    return reminder
