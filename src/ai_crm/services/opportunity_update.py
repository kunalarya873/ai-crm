from typing import Any, cast

from sqlalchemy import update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.deps import RequestContext
from ..domain import (
    ALLOWED_OPPORTUNITY_STAGE_TRANSITIONS,
    InvalidRequestError,
    InvalidTransitionError,
    VersionConflictError,
    validate_transition,
)
from ..models import Opportunity
from ..schemas import OpportunityUpdate
from .common import require_version, utc_now
from .events import _record_update_events
from .lookups import _validate_relationships, get_opportunity_for_tenant

__all__ = [
    "update_opportunity",
]


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
