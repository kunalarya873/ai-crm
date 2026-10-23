from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from .api.deps import RequestContext
from .audit import record_audit, record_outbox_event
from .domain import (
    ALLOWED_CONTACT_TRANSITIONS,
    ALLOWED_OPPORTUNITY_STAGE_TRANSITIONS,
    ALLOWED_TASK_TRANSITIONS,
    ConflictError,
    InvalidRequestError,
    InvalidTransitionError,
    NotFoundError,
    PreconditionRequiredError,
    VersionConflictError,
    normalize_name,
    validate_transition,
)
from .models import Activity, Company, Contact, Opportunity, Task
from .schemas import (
    ActivityCreate,
    CompanyCreate,
    CompanyUpdate,
    ContactCreate,
    ContactUpdate,
    OpportunityCreate,
    OpportunityUpdate,
    TaskCreate,
    TaskUpdate,
)


def utc_now() -> datetime:
    return datetime.now(UTC)


def json_safe(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    return value


def require_version(expected_version: int | None) -> int:
    if expected_version is None:
        raise PreconditionRequiredError("If-Match header is required")
    if expected_version < 1:
        raise ValueError("If-Match must contain a positive integer version")
    return expected_version


async def get_company_for_tenant(
    session: AsyncSession,
    context: RequestContext,
    company_id: str,
) -> Company:
    company = await session.scalar(
        select(Company).where(Company.id == company_id, Company.tenant_id == context.tenant_id)
    )
    if company is None:
        raise NotFoundError("Company not found")
    return company


async def get_contact_for_tenant(
    session: AsyncSession,
    context: RequestContext,
    contact_id: str,
) -> Contact:
    contact = await session.scalar(
        select(Contact).where(Contact.id == contact_id, Contact.tenant_id == context.tenant_id)
    )
    if contact is None:
        raise NotFoundError("Contact not found")
    return contact


async def get_opportunity_for_tenant(
    session: AsyncSession,
    context: RequestContext,
    opportunity_id: str,
) -> Opportunity:
    opportunity = await session.scalar(
        select(Opportunity).where(
            Opportunity.id == opportunity_id,
            Opportunity.tenant_id == context.tenant_id,
        )
    )
    if opportunity is None:
        raise NotFoundError("Opportunity not found")
    return opportunity


async def _validate_relationships(
    session: AsyncSession,
    context: RequestContext,
    *,
    company_id: str | None = None,
    contact_id: str | None = None,
    opportunity_id: str | None = None,
) -> None:
    if company_id is not None:
        await get_company_for_tenant(session, context, company_id)
    if contact_id is not None:
        await get_contact_for_tenant(session, context, contact_id)
    if opportunity_id is not None:
        await get_opportunity_for_tenant(session, context, opportunity_id)


async def create_contact(
    session: AsyncSession,
    context: RequestContext,
    payload: ContactCreate,
) -> Contact:
    if payload.status not in ALLOWED_CONTACT_TRANSITIONS:
        raise InvalidRequestError("Invalid contact status")
    await _validate_relationships(session, context, company_id=payload.company_id)
    contact = Contact(tenant_id=context.tenant_id, **payload.model_dump())
    session.add(contact)
    await session.flush()
    await record_audit(
        session=session,
        context=context,
        action="contact.created",
        entity_type="contact",
        entity_id=contact.id,
        details={"version": contact.version},
    )
    await record_outbox_event(
        session=session,
        context=context,
        event_type="contact.created",
        aggregate_type="contact",
        aggregate_id=contact.id,
        payload={"version": contact.version},
    )
    await session.commit()
    await session.refresh(contact)
    return contact


async def list_contacts(
    session: AsyncSession,
    context: RequestContext,
    limit: int,
    offset: int,
    *,
    company_id: str | None = None,
    owner_id: str | None = None,
    contact_status: str | None = None,
    query: str | None = None,
    archived: bool = False,
) -> Sequence[Contact]:
    statement = select(Contact).where(Contact.tenant_id == context.tenant_id)
    if company_id is not None:
        statement = statement.where(Contact.company_id == company_id)
    if owner_id is not None:
        statement = statement.where(Contact.owner_id == owner_id)
    if contact_status is not None:
        statement = statement.where(Contact.status == contact_status)
    if not archived:
        statement = statement.where(Contact.archived_at.is_(None))
    if query:
        pattern = f"%{query.strip()}%"
        statement = statement.where(
            Contact.first_name.ilike(pattern)
            | Contact.last_name.ilike(pattern)
            | Contact.email.ilike(pattern)
        )
    result = await session.scalars(
        statement.order_by(Contact.created_at.desc()).offset(offset).limit(limit)
    )
    return result.all()


async def get_contact(
    session: AsyncSession,
    context: RequestContext,
    contact_id: str,
) -> Contact | None:
    return await session.scalar(
        select(Contact).where(
            Contact.id == contact_id,
            Contact.tenant_id == context.tenant_id,
        )
    )


async def update_contact(
    session: AsyncSession,
    context: RequestContext,
    contact_id: str,
    payload: ContactUpdate,
    expected_version: int | None,
) -> Contact:
    expected = require_version(expected_version)
    contact = await get_contact_for_tenant(session, context, contact_id)
    if contact.version != expected:
        raise VersionConflictError("record_version_conflict")
    changes = payload.model_dump(exclude_unset=True)
    archived = changes.pop("archived", None)
    if not changes and archived is None:
        raise InvalidRequestError("At least one field is required")
    if "company_id" in changes:
        await _validate_relationships(session, context, company_id=changes["company_id"])
    if "status" in changes:
        validate_transition(contact.status, changes["status"], ALLOWED_CONTACT_TRANSITIONS)
    if archived is not None:
        changes["archived_at"] = utc_now() if archived else None
    old_state = {key: getattr(contact, key) for key in changes if hasattr(contact, key)}
    changes.update(version=expected + 1, updated_at=utc_now())
    result = cast(
        CursorResult[Any],
        await session.execute(
            update(Contact)
            .where(
                Contact.id == contact_id,
                Contact.tenant_id == context.tenant_id,
                Contact.version == expected,
            )
            .values(**changes)
        ),
    )
    if result.rowcount != 1:
        await session.rollback()
        raise VersionConflictError("record_version_conflict")
    await record_audit(
        session=session,
        context=context,
        action="contact.updated",
        entity_type="contact",
        entity_id=contact_id,
        details={"old": old_state, "new": changes, "version": expected + 1},
    )
    await record_outbox_event(
        session=session,
        context=context,
        event_type="contact.updated",
        aggregate_type="contact",
        aggregate_id=contact_id,
        payload={"old": old_state, "new": changes, "version": expected + 1},
    )
    await session.commit()
    await session.refresh(contact)
    return contact


async def create_company(
    session: AsyncSession,
    context: RequestContext,
    payload: CompanyCreate,
) -> Company:
    normalized_name = normalize_name(payload.name)
    existing = await session.scalar(
        select(Company).where(
            Company.tenant_id == context.tenant_id,
            Company.normalized_name == normalized_name,
        )
    )
    if existing is not None:
        raise ConflictError("A company with this name already exists in this tenant")
    company = Company(
        tenant_id=context.tenant_id,
        normalized_name=normalized_name,
        **payload.model_dump(),
    )
    session.add(company)
    await session.flush()
    await record_audit(
        session=session,
        context=context,
        action="company.created",
        entity_type="company",
        entity_id=company.id,
        details={"version": company.version},
    )
    await record_outbox_event(
        session=session,
        context=context,
        event_type="company.created",
        aggregate_type="company",
        aggregate_id=company.id,
        payload={"version": company.version},
    )
    await session.commit()
    await session.refresh(company)
    return company


async def list_companies(
    session: AsyncSession,
    context: RequestContext,
    limit: int,
    offset: int,
) -> Sequence[Company]:
    result = await session.scalars(
        select(Company)
        .where(Company.tenant_id == context.tenant_id, Company.archived_at.is_(None))
        .order_by(Company.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return result.all()


async def update_company(
    session: AsyncSession,
    context: RequestContext,
    company_id: str,
    payload: CompanyUpdate,
    expected_version: int | None,
) -> Company:
    expected = require_version(expected_version)
    company = await get_company_for_tenant(session, context, company_id)
    if company.version != expected:
        raise VersionConflictError("record_version_conflict")
    changes = payload.model_dump(exclude_unset=True)
    archived = changes.pop("archived", None)
    if not changes and archived is None:
        raise InvalidRequestError("At least one field is required")
    if "name" in changes:
        normalized_name = normalize_name(changes["name"])
        duplicate = await session.scalar(
            select(Company).where(
                Company.tenant_id == context.tenant_id,
                Company.normalized_name == normalized_name,
                Company.id != company_id,
            )
        )
        if duplicate is not None:
            raise ConflictError("A company with this name already exists in this tenant")
        changes["normalized_name"] = normalized_name
    if archived is not None:
        changes["archived_at"] = utc_now() if archived else None
    old_state = {key: getattr(company, key) for key in changes if hasattr(company, key)}
    changes.update(version=expected + 1, updated_at=utc_now())
    result = cast(
        CursorResult[Any],
        await session.execute(
            update(Company)
            .where(
                Company.id == company_id,
                Company.tenant_id == context.tenant_id,
                Company.version == expected,
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
        action="company.updated",
        entity_type="company",
        entity_id=company_id,
        old_state=old_state,
        new_state=changes,
        version=expected + 1,
    )
    await session.commit()
    await session.refresh(company)
    return company


async def create_opportunity(
    session: AsyncSession,
    context: RequestContext,
    payload: OpportunityCreate,
) -> Opportunity:
    if not payload.company_id and not payload.contact_id:
        raise InvalidRequestError("An opportunity must be linked to a company or contact")
    if payload.stage not in ALLOWED_OPPORTUNITY_STAGE_TRANSITIONS:
        raise InvalidRequestError("Invalid opportunity stage")
    if payload.status not in {"open", "won", "lost"}:
        raise InvalidRequestError("Invalid opportunity status")
    await _validate_relationships(
        session,
        context,
        company_id=payload.company_id,
        contact_id=payload.contact_id,
    )
    opportunity = Opportunity(tenant_id=context.tenant_id, **payload.model_dump())
    session.add(opportunity)
    await session.flush()
    await _record_create_events(
        session,
        context,
        action="opportunity.created",
        entity_type="opportunity",
        entity_id=opportunity.id,
        version=opportunity.version,
    )
    await session.commit()
    await session.refresh(opportunity)
    return opportunity


async def list_opportunities(
    session: AsyncSession,
    context: RequestContext,
    limit: int,
    offset: int,
    *,
    stage: str | None = None,
    owner_id: str | None = None,
    company_id: str | None = None,
    opportunity_status: str | None = None,
) -> Sequence[Opportunity]:
    statement = select(Opportunity).where(
        Opportunity.tenant_id == context.tenant_id,
        Opportunity.archived_at.is_(None),
    )
    if stage:
        statement = statement.where(Opportunity.stage == stage)
    if owner_id:
        statement = statement.where(Opportunity.owner_id == owner_id)
    if company_id:
        statement = statement.where(Opportunity.company_id == company_id)
    if opportunity_status:
        statement = statement.where(Opportunity.status == opportunity_status)
    result = await session.scalars(
        statement.order_by(Opportunity.created_at.desc()).offset(offset).limit(limit)
    )
    return result.all()


async def update_opportunity(
    session: AsyncSession,
    context: RequestContext,
    opportunity_id: str,
    payload: OpportunityUpdate,
    expected_version: int | None,
) -> Opportunity:
    expected = require_version(expected_version)
    opportunity = await get_opportunity_for_tenant(session, context, opportunity_id)
    if opportunity.version != expected:
        raise VersionConflictError("record_version_conflict")
    changes = payload.model_dump(exclude_unset=True)
    archived = changes.pop("archived", None)
    if not changes and archived is None:
        raise InvalidRequestError("At least one field is required")
    await _validate_relationships(
        session,
        context,
        company_id=changes.get("company_id", opportunity.company_id),
        contact_id=changes.get("contact_id", opportunity.contact_id),
    )
    if "stage" in changes:
        validate_transition(
            opportunity.stage,
            changes["stage"],
            ALLOWED_OPPORTUNITY_STAGE_TRANSITIONS,
        )
        if changes["stage"] == "closed_won":
            changes["status"] = "won"
        elif changes["stage"] == "closed_lost":
            changes["status"] = "lost"
    if "status" in changes and changes["status"] not in {"open", "won", "lost"}:
        raise InvalidTransitionError("Invalid opportunity status")
    if archived is not None:
        changes["archived_at"] = utc_now() if archived else None
    old_state = {key: getattr(opportunity, key) for key in changes if hasattr(opportunity, key)}
    changes.update(version=expected + 1, updated_at=utc_now())
    result = cast(
        CursorResult[Any],
        await session.execute(
            update(Opportunity)
            .where(
                Opportunity.id == opportunity_id,
                Opportunity.tenant_id == context.tenant_id,
                Opportunity.version == expected,
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
        action="opportunity.updated",
        entity_type="opportunity",
        entity_id=opportunity_id,
        old_state=old_state,
        new_state=changes,
        version=expected + 1,
    )
    await session.commit()
    await session.refresh(opportunity)
    return opportunity


async def get_opportunity(
    session: AsyncSession,
    context: RequestContext,
    opportunity_id: str,
) -> Opportunity | None:
    return await session.scalar(
        select(Opportunity).where(
            Opportunity.id == opportunity_id,
            Opportunity.tenant_id == context.tenant_id,
        )
    )


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


async def create_task(
    session: AsyncSession,
    context: RequestContext,
    payload: TaskCreate,
) -> Task:
    if payload.status not in ALLOWED_TASK_TRANSITIONS:
        raise InvalidRequestError("Invalid task status")
    await _validate_relationships(
        session,
        context,
        contact_id=payload.contact_id,
        opportunity_id=payload.opportunity_id,
    )
    values = payload.model_dump()
    completed_at = utc_now() if values["status"] == "completed" else None
    task = Task(tenant_id=context.tenant_id, completed_at=completed_at, **values)
    session.add(task)
    await session.flush()
    await _record_create_events(
        session,
        context,
        action="task.created",
        entity_type="task",
        entity_id=task.id,
        version=task.version,
    )
    await session.commit()
    await session.refresh(task)
    return task


async def list_tasks(
    session: AsyncSession,
    context: RequestContext,
    limit: int,
    offset: int,
    *,
    task_status: str | None = None,
    assignee_id: str | None = None,
    contact_id: str | None = None,
    opportunity_id: str | None = None,
    overdue: bool = False,
) -> Sequence[Task]:
    statement = select(Task).where(
        Task.tenant_id == context.tenant_id,
        Task.archived_at.is_(None),
    )
    if task_status:
        statement = statement.where(Task.status == task_status)
    if assignee_id:
        statement = statement.where(Task.assignee_id == assignee_id)
    if contact_id:
        statement = statement.where(Task.contact_id == contact_id)
    if opportunity_id:
        statement = statement.where(Task.opportunity_id == opportunity_id)
    if overdue:
        statement = statement.where(
            Task.due_at < utc_now(),
            Task.status.notin_(["completed", "cancelled"]),
        )
    result = await session.scalars(
        statement.order_by(Task.created_at.desc()).offset(offset).limit(limit)
    )
    return result.all()


async def get_task(
    session: AsyncSession,
    context: RequestContext,
    task_id: str,
) -> Task | None:
    return await session.scalar(
        select(Task).where(Task.id == task_id, Task.tenant_id == context.tenant_id)
    )


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


async def _record_create_events(
    session: AsyncSession,
    context: RequestContext,
    *,
    action: str,
    entity_type: str,
    entity_id: str,
    version: int | None,
) -> None:
    details = {"version": version} if version is not None else {}
    await record_audit(
        session=session,
        context=context,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details=details,
    )
    await record_outbox_event(
        session=session,
        context=context,
        event_type=action,
        aggregate_type=entity_type,
        aggregate_id=entity_id,
        payload=details,
    )


async def _record_update_events(
    session: AsyncSession,
    context: RequestContext,
    *,
    action: str,
    entity_type: str,
    entity_id: str,
    old_state: dict[str, object],
    new_state: dict[str, object],
    version: int,
) -> None:
    details = {
        "old": json_safe(old_state),
        "new": json_safe(new_state),
        "version": version,
    }
    await record_audit(
        session=session,
        context=context,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details=details,
    )
    await record_outbox_event(
        session=session,
        context=context,
        event_type=action,
        aggregate_type=entity_type,
        aggregate_id=entity_id,
        payload=details,
    )
