from sqlalchemy.ext.asyncio import AsyncSession

from ..api.deps import RequestContext
from ..audit import record_audit, record_outbox_event
from .common import json_safe

__all__ = [
    "_record_create_events", "_record_update_events",
]


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
