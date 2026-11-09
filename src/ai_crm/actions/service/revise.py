from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import RequestContext
from ...domain import InvalidTransitionError
from ...models import ActionProposal, utc_now
from ...permissions import Permission
from ...schemas import ActionDecision, ActionProposalEdit
from ..registry import get_action_definition
from .common import _check_version, _hash_payload, _require_permission
from .lifecycle import _proposal_event
from .reads import _expiry, get_proposal

__all__ = [
    "edit_proposal", "revoke_proposal",
]


async def edit_proposal(
    session: AsyncSession,
    context: RequestContext,
    proposal_id: str,
    expected_version: int | None,
    payload: ActionProposalEdit,
) -> ActionProposal:
    _require_permission(context, Permission.ACTIONS_PROPOSE)
    proposal = await get_proposal(session, context, proposal_id)
    _check_version(proposal, expected_version)
    if proposal.status not in {"proposed", "edited", "approved"}:
        raise InvalidTransitionError(f"Cannot edit proposal in state {proposal.status}")
    definition = get_action_definition(proposal.action_type)
    normalized = definition.validate(payload.payload)
    normalized_payload = normalized.model_dump(mode="json", exclude_unset=True)
    proposal.payload = normalized_payload
    proposal.request_hash = _hash_payload(proposal.action_type, normalized_payload)
    if payload.evidence_refs is not None:
        proposal.evidence_refs = payload.evidence_refs
    if payload.affected_resources is not None:
        proposal.affected_resources = payload.affected_resources
    if payload.intended_changes is not None:
        proposal.intended_changes = payload.intended_changes
    if payload.expected_side_effects is not None:
        proposal.expected_side_effects = payload.expected_side_effects
    if payload.expires_at is not None:
        proposal.expires_at = _expiry(payload.expires_at)
    proposal.status = "edited"
    proposal.last_edited_by = context.actor_id
    proposal.approved_by = None
    proposal.approved_at = None
    proposal.decision_reason = None
    proposal.version += 1
    proposal.updated_at = utc_now()
    await _proposal_event(session, context, proposal, "action.proposal.edited", None)
    await session.commit()
    await session.refresh(proposal)
    return proposal


async def revoke_proposal(
    session: AsyncSession,
    context: RequestContext,
    proposal_id: str,
    expected_version: int | None,
    decision: ActionDecision,
) -> ActionProposal:
    _require_permission(context, Permission.ACTIONS_PROPOSE)
    proposal = await get_proposal(session, context, proposal_id)
    _check_version(proposal, expected_version)
    if proposal.status not in {"proposed", "edited", "approved", "failed", "recoverable"}:
        raise InvalidTransitionError(f"Cannot revoke proposal in state {proposal.status}")
    proposal.status = "revoked"
    proposal.decision_reason = decision.reason
    proposal.version += 1
    proposal.updated_at = utc_now()
    await _proposal_event(session, context, proposal, "action.proposal.revoked", decision.reason)
    await session.commit()
    await session.refresh(proposal)
    return proposal
