from typing import Any, cast

from pydantic import BaseModel
from sqlalchemy import update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import RequestContext
from ...audit import record_audit, record_outbox_event
from ...domain import InvalidRequestError, InvalidTransitionError, VersionConflictError
from ...models import Contact, utc_now
from ...schemas import ContactUpdate
from ..registry import ContactAssignOwnerAction, ContactUpdateAction
from .common import _json_safe
from .effects_tasks import _get_contact, _validate_relationships

__all__ = [
    "_apply_contact_update", "_assign_contact_owner", "_update_contact",
]


async def _apply_contact_update(
    session: AsyncSession,
    context: RequestContext,
    contact: Contact,
    changes: ContactUpdate,
    expected_version: int,
) -> dict[str, object]:
    if contact.version != expected_version:
        raise VersionConflictError("record_version_conflict")
    values = changes.model_dump(exclude_unset=True)
    archived = values.pop("archived", None)
    if not values and archived is None:
        raise InvalidRequestError("At least one contact field is required")
    if "company_id" in values:
        await _validate_relationships(session, context, company_id=values["company_id"])
    if "status" in values:
        allowed = {
            "lead": {"qualified", "lost"},
            "qualified": {"customer", "lost"},
            "customer": {"lost"},
            "lost": set(),
        }
        if values["status"] != contact.status and values["status"] not in allowed.get(
            contact.status, set()
        ):
            raise InvalidTransitionError(
                f"Cannot transition contact from {contact.status} to {values['status']}"
            )
    if archived is not None:
        values["archived_at"] = utc_now() if archived else None
    old_state = {key: _json_safe(getattr(contact, key)) for key in values if hasattr(contact, key)}
    update_values = {**values, "version": expected_version + 1, "updated_at": utc_now()}
    result = cast(
        CursorResult[Any],
        await session.execute(
            update(Contact)
            .where(
                Contact.id == contact.id,
                Contact.tenant_id == context.tenant_id,
                Contact.version == expected_version,
            )
            .values(**update_values)
        ),
    )
    if result.rowcount != 1:
        raise VersionConflictError("record_version_conflict")
    await record_audit(
        session,
        context,
        "contact.updated",
        "contact",
        contact.id,
        details={"old": old_state, "new": _json_safe(update_values), "via": "action_execution"},
    )
    await record_outbox_event(
        session,
        context,
        "contact.updated",
        "contact",
        contact.id,
        {"new": _json_safe(update_values), "via": "action_execution"},
    )
    return {"entity_type": "contact", "entity_id": contact.id, "version": expected_version + 1}


async def _update_contact(
    session: AsyncSession,
    context: RequestContext,
    payload: BaseModel,
) -> dict[str, object]:
    action = ContactUpdateAction.model_validate(payload.model_dump(exclude_unset=True))
    contact = await _get_contact(session, context, action.contact_id)
    return await _apply_contact_update(
        session,
        context,
        contact,
        action.changes,
        action.expected_version,
    )


async def _assign_contact_owner(
    session: AsyncSession,
    context: RequestContext,
    payload: BaseModel,
) -> dict[str, object]:
    action = ContactAssignOwnerAction.model_validate(payload.model_dump())
    contact = await _get_contact(session, context, action.contact_id)
    return await _apply_contact_update(
        session,
        context,
        contact,
        ContactUpdate(owner_id=action.owner_id),
        action.expected_version,
    )
