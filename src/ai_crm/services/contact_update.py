from typing import Any, cast

from sqlalchemy import update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.deps import RequestContext
from ..audit import record_audit, record_outbox_event
from ..domain import (
    ALLOWED_CONTACT_TRANSITIONS,
    InvalidRequestError,
    VersionConflictError,
    validate_transition,
)
from ..lifecycle import ensure_not_erased
from ..models import Contact
from ..schemas import ContactUpdate
from .common import json_safe, require_version, utc_now
from .lookups import _validate_relationships, get_contact_for_tenant

__all__ = [
    "update_contact",
]


async def update_contact(
    session: AsyncSession,
    context: RequestContext,
    contact_id: str,
    payload: ContactUpdate,
    expected_version: int | None,
) -> Contact:
    expected = require_version(expected_version)
    contact = await get_contact_for_tenant(session, context, contact_id)
    await ensure_not_erased(session, context, "contacts", contact_id)
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
        details={
            "old": json_safe(old_state),
            "new": json_safe(changes),
            "version": expected + 1,
        },
    )
    await record_outbox_event(
        session=session,
        context=context,
        event_type="contact.updated",
        aggregate_type="contact",
        aggregate_id=contact_id,
        payload={
            "old": json_safe(old_state),
            "new": json_safe(changes),
            "version": expected + 1,
        },
    )
    await session.commit()
    await session.refresh(contact)
    return contact
