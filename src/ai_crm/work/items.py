from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.deps import RequestContext
from ..audit import record_audit, record_outbox_event
from ..domain import ConflictError, InvalidRequestError, NotFoundError
from ..models import (
    Contact,
    Opportunity,
    ReminderDelivery,
    WorkItem,
    WorkItemTransition,
    utc_now,
)
from ..schemas import ReminderCreate, WorkItemCreate, WorkItemTransitionRequest, WorkItemUpdate
from .domain import (
    require_aware_datetime,
    validate_timezone,
    validate_work_item_status,
    validate_work_item_transition,
    validate_work_item_type,
)
from .jobs import create_job_in_session


def _same_instant(left, right) -> bool:
    if left.tzinfo is None:
        left = left.replace(tzinfo=right.tzinfo)
    return left == right


async def get_work_item(
    session: AsyncSession,
    context: RequestContext,
    work_item_id: str,
) -> WorkItem:
    item = await session.scalar(
        select(WorkItem).where(
            WorkItem.id == work_item_id,
            WorkItem.tenant_id == context.tenant_id,
        )
    )
    if item is None:
        raise NotFoundError("Work item not found")
    return item


async def _validate_references(
    session: AsyncSession,
    context: RequestContext,
    *,
    contact_id: str | None = None,
    opportunity_id: str | None = None,
    dependency_ids: list[str] | None = None,
    current_id: str | None = None,
) -> None:
    if contact_id is not None:
        contact = await session.scalar(
            select(Contact).where(
                Contact.id == contact_id,
                Contact.tenant_id == context.tenant_id,
            )
        )
        if contact is None:
            raise NotFoundError("Contact not found")
    if opportunity_id is not None:
        opportunity = await session.scalar(
            select(Opportunity).where(
                Opportunity.id == opportunity_id,
                Opportunity.tenant_id == context.tenant_id,
            )
        )
        if opportunity is None:
            raise NotFoundError("Opportunity not found")
    dependency_ids = dependency_ids or []
    if current_id and current_id in dependency_ids:
        raise InvalidRequestError("A work item cannot depend on itself")
    if len(dependency_ids) != len(set(dependency_ids)):
        raise InvalidRequestError("Work item dependencies must be unique")
    if dependency_ids:
        result = await session.scalars(
            select(WorkItem).where(
                WorkItem.tenant_id == context.tenant_id,
                WorkItem.id.in_(dependency_ids),
            )
        )
        found = {item.id for item in result}
        if found != set(dependency_ids):
            raise NotFoundError("A work item dependency was not found")


async def create_work_item(
    session: AsyncSession,
    context: RequestContext,
    payload: WorkItemCreate,
) -> WorkItem:
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
    await session.commit()
    await session.refresh(item)
    return item


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


async def update_work_item(
    session: AsyncSession,
    context: RequestContext,
    work_item_id: str,
    payload: WorkItemUpdate,
    expected_version: int | None,
) -> WorkItem:
    if expected_version is None:
        raise InvalidRequestError("If-Match header is required")
    item = await get_work_item(session, context, work_item_id)
    if item.version != expected_version:
        raise ConflictError("record_version_conflict")
    changes = payload.model_dump(exclude_unset=True)
    archived = changes.pop("archived", None)
    if not changes and archived is None:
        raise InvalidRequestError("At least one field is required")
    if "timezone" in changes:
        changes["timezone"] = validate_timezone(changes["timezone"])
    if "due_at" in changes:
        require_aware_datetime(changes["due_at"], "due_at")
    await _validate_references(
        session,
        context,
        contact_id=item.contact_id,
        opportunity_id=item.opportunity_id,
        dependency_ids=changes.get("depends_on_ids", item.depends_on_ids),
        current_id=item.id,
    )
    for key, value in changes.items():
        setattr(item, key, value)
    if archived is not None:
        item.archived_at = utc_now() if archived else None
    item.version = expected_version + 1
    item.updated_at = utc_now()
    await record_audit(
        session,
        context,
        "work_item.updated",
        "work_item",
        item.id,
        details={"version": item.version, "fields": list(changes)},
    )
    await record_outbox_event(
        session,
        context,
        "work_item.updated",
        "work_item",
        item.id,
        {"version": item.version, "fields": list(changes)},
    )
    await session.commit()
    await session.refresh(item)
    return item


async def transition_work_item(
    session: AsyncSession,
    context: RequestContext,
    work_item_id: str,
    payload: WorkItemTransitionRequest,
    expected_version: int | None,
) -> WorkItem:
    if expected_version is None:
        raise InvalidRequestError("If-Match header is required")
    item = await get_work_item(session, context, work_item_id)
    if item.version != expected_version:
        raise ConflictError("record_version_conflict")
    validate_work_item_transition(item.status, payload.to_status)
    if payload.to_status == "completed" and not (payload.evidence or item.completion_evidence):
        raise InvalidRequestError("Completion evidence is required")
    if payload.to_status == "blocked" and not payload.reason:
        raise InvalidRequestError("A blocked work item requires a reason")
    if payload.to_status in {"in_progress", "completed"} and item.depends_on_ids:
        dependencies = await session.scalars(
            select(WorkItem).where(WorkItem.id.in_(item.depends_on_ids))
        )
        if any(dependency.status != "completed" for dependency in dependencies):
            raise ConflictError("Work item dependencies are not completed")
    previous_status = item.status
    item.status = payload.to_status
    item.version = expected_version + 1
    item.updated_at = utc_now()
    if payload.evidence:
        item.completion_evidence = payload.evidence
    if payload.to_status == "blocked":
        item.blocked_reason = payload.reason
    elif payload.to_status != "blocked":
        item.blocked_reason = None
    if payload.to_status == "completed":
        item.completed_at = utc_now()
    elif previous_status == "completed":
        item.completed_at = None
    session.add(
        WorkItemTransition(
            tenant_id=context.tenant_id,
            work_item_id=item.id,
            from_status=previous_status,
            to_status=item.status,
            actor_id=context.actor_id,
            reason=payload.reason,
            evidence=payload.evidence,
        )
    )
    await record_audit(
        session,
        context,
        "work_item.transitioned",
        "work_item",
        item.id,
        details={"from": previous_status, "to": item.status},
    )
    await record_outbox_event(
        session,
        context,
        "work_item.transitioned",
        "work_item",
        item.id,
        {"from": previous_status, "to": item.status},
    )
    await session.commit()
    await session.refresh(item)
    return item


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
