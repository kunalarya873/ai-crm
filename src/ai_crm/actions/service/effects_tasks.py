from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import RequestContext
from ...audit import record_audit, record_outbox_event
from ...domain import InvalidRequestError, NotFoundError
from ...models import Contact, Opportunity, Task, utc_now
from ...schemas import TaskCreate

__all__ = [
    "_create_task", "_get_contact", "_validate_relationships",
]


async def _validate_relationships(
    session: AsyncSession,
    context: RequestContext,
    *,
    contact_id: str | None = None,
    company_id: str | None = None,
    opportunity_id: str | None = None,
) -> None:
    for model, identifier, label in (
        (Contact, contact_id, "Contact"),
        (Opportunity, opportunity_id, "Opportunity"),
    ):
        if identifier is not None:
            found = await session.scalar(
                select(model).where(model.id == identifier, model.tenant_id == context.tenant_id)
            )
            if found is None:
                raise NotFoundError(f"{label} not found")
    if company_id is not None:
        from ...models import Company

        found = await session.scalar(
            select(Company).where(Company.id == company_id, Company.tenant_id == context.tenant_id)
        )
        if found is None:
            raise NotFoundError("Company not found")


async def _create_task(
    session: AsyncSession,
    context: RequestContext,
    payload: BaseModel,
) -> dict[str, object]:
    task_payload = TaskCreate.model_validate(payload.model_dump(exclude_unset=True))
    if task_payload.status not in {"open", "in_progress", "completed", "cancelled"}:
        raise InvalidRequestError("Invalid task status")
    await _validate_relationships(
        session,
        context,
        contact_id=task_payload.contact_id,
        opportunity_id=task_payload.opportunity_id,
    )
    values = task_payload.model_dump()
    task = Task(
        tenant_id=context.tenant_id,
        completed_at=utc_now() if values["status"] == "completed" else None,
        **values,
    )
    session.add(task)
    await session.flush()
    await record_audit(
        session,
        context,
        "task.created",
        "task",
        task.id,
        details={"version": task.version, "via": "action_execution"},
    )
    await record_outbox_event(
        session,
        context,
        "task.created",
        "task",
        task.id,
        {"version": task.version, "via": "action_execution"},
    )
    return {"entity_type": "task", "entity_id": task.id, "version": task.version}


async def _get_contact(
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
