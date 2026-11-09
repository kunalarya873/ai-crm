from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.deps import RequestContext
from ..audit import record_audit, record_outbox_event
from ..domain import (
    ALLOWED_CONTACT_TRANSITIONS,
    InvalidRequestError,
)
from ..models import Contact
from ..pagination import page_statement
from ..schemas import (
    ContactCreate,
)
from .lookups import _validate_relationships

__all__ = [
    "create_contact", "get_contact", "list_contacts",
]


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
    cursor: str | None = None,
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
    result = await session.scalars(page_statement(statement, Contact, limit, offset, cursor))
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
