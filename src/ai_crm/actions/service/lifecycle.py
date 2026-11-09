from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import RequestContext
from ...audit import record_audit, record_outbox_event
from ...models import ActionProposal, utc_now
from ...permissions import Permission
from ...schemas import ActionDryRunResponse
from ..registry import get_action_definition
from .common import _require_permission
from .reads import _resource_refs

__all__ = [
    "_proposal_event", "dry_run_action", "expire_proposals",
]


async def _proposal_event(
    session: AsyncSession,
    context: RequestContext,
    proposal: ActionProposal,
    event_type: str,
    reason: str | None,
) -> None:
    await record_audit(
        session,
        context,
        event_type,
        "action_proposal",
        proposal.id,
        reason=reason,
        details={"status": proposal.status, "version": proposal.version},
    )
    await record_outbox_event(
        session,
        context,
        event_type,
        "action_proposal",
        proposal.id,
        {"status": proposal.status, "version": proposal.version},
    )


async def expire_proposals(
    session: AsyncSession,
    context: RequestContext,
) -> list[ActionProposal]:
    _require_permission(context, Permission.ACTIONS_RECOVER)
    now = utc_now()
    result = await session.scalars(
        select(ActionProposal).where(
            ActionProposal.tenant_id == context.tenant_id,
            ActionProposal.status.in_({"proposed", "edited", "approved"}),
            ActionProposal.expires_at <= now,
        )
    )
    proposals = list(result)
    for proposal in proposals:
        proposal.status = "expired"
        proposal.version += 1
        proposal.updated_at = now
        await _proposal_event(session, context, proposal, "action.proposal.expired", "expiration")
    await session.commit()
    for proposal in proposals:
        await session.refresh(proposal)
    return proposals


async def dry_run_action(
    context: RequestContext,
    action_type: str,
    payload: dict[str, object],
) -> ActionDryRunResponse:
    _require_permission(context, Permission.ACTIONS_PROPOSE)
    definition = get_action_definition(action_type)
    _require_permission(context, definition.required_permission)
    normalized = definition.validate(payload)
    normalized_payload = normalized.model_dump(mode="json", exclude_unset=True)
    return ActionDryRunResponse(
        action_type=definition.action_type,
        action_version=definition.version,
        required_permission=definition.required_permission.value,
        risk_level=definition.risk_level,
        requires_approval=definition.requires_approval,
        valid=True,
        normalized_payload=normalized_payload,
        affected_resources=_resource_refs(definition.action_type, normalized_payload),
        intended_changes=normalized_payload,
        expected_side_effects=list(definition.expected_side_effects),
    )
