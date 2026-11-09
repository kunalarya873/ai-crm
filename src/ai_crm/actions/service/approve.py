from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import RequestContext
from ...audit import record_audit
from ...domain import InvalidTransitionError, SeparationOfDutiesError
from ...models import ActionProposal, utc_now
from ...permissions import Permission
from ...schemas import ActionDecision
from ..registry import get_action_definition
from .common import _check_version, _ensure_not_expired, _require_permission
from .lifecycle import _proposal_event
from .reads import get_proposal

__all__ = [
    "approve_proposal", "reject_proposal",
]


async def approve_proposal(
    session: AsyncSession,
    context: RequestContext,
    proposal_id: str,
    expected_version: int | None,
    decision: ActionDecision,
) -> ActionProposal:
    _require_permission(context, Permission.ACTIONS_APPROVE)
    proposal = await get_proposal(session, context, proposal_id)
    _check_version(proposal, expected_version)
    _ensure_not_expired(proposal)
    if proposal.status not in {"proposed", "edited"}:
        raise InvalidTransitionError(f"Cannot approve proposal in state {proposal.status}")
    if context.actor_id in {proposal.requested_by, proposal.last_edited_by}:
        await record_audit(
            session,
            context,
            "action.proposal.approve",
            "action_proposal",
            proposal.id,
            outcome="denied",
            reason="self_approval",
        )
        await session.commit()
        raise SeparationOfDutiesError(
            "Proposals cannot be approved by their requester or last editor"
        )
    definition = get_action_definition(proposal.action_type)
    _require_permission(context, definition.required_permission)
    definition.validate(proposal.payload)
    proposal.status = "approved"
    proposal.approved_by = context.actor_id
    proposal.approved_at = utc_now()
    proposal.decision_reason = decision.reason
    proposal.version += 1
    proposal.updated_at = utc_now()
    await _proposal_event(session, context, proposal, "action.proposal.approved", decision.reason)
    await session.commit()
    await session.refresh(proposal)
    return proposal


async def reject_proposal(
    session: AsyncSession,
    context: RequestContext,
    proposal_id: str,
    expected_version: int | None,
    decision: ActionDecision,
) -> ActionProposal:
    _require_permission(context, Permission.ACTIONS_APPROVE)
    proposal = await get_proposal(session, context, proposal_id)
    _check_version(proposal, expected_version)
    if proposal.status not in {"proposed", "edited", "approved"}:
        raise InvalidTransitionError(f"Cannot reject proposal in state {proposal.status}")
    proposal.status = "rejected"
    proposal.rejected_by = context.actor_id
    proposal.decision_reason = decision.reason
    proposal.version += 1
    proposal.updated_at = utc_now()
    await _proposal_event(session, context, proposal, "action.proposal.rejected", decision.reason)
    await session.commit()
    await session.refresh(proposal)
    return proposal
