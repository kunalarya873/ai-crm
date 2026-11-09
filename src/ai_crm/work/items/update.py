from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import RequestContext
from ...audit import record_audit, record_outbox_event
from ...domain import ConflictError, InvalidRequestError
from ...models import WorkItem, utc_now
from ...schemas import WorkItemUpdate
from ..domain import require_aware_datetime, validate_timezone
from .refs import _validate_references, get_work_item

__all__ = [
    "update_work_item",
]


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
