from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import RequestContext
from ...audit import record_audit, record_outbox_event
from ...domain import ConflictError, InvalidRequestError
from ...models import WorkItem, WorkItemTransition, utc_now
from ...schemas import WorkItemTransitionRequest
from ..domain import (
    validate_work_item_transition,
)
from .refs import get_work_item

__all__ = [
    "transition_work_item",
]


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
