from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import RequestContext
from ...audit import record_audit, record_outbox_event
from ...domain import ConflictError, InvalidRequestError, NotFoundError
from ...models import ActionProposal
from ...permissions import Permission
from ...schemas import ActionProposalCreate
from ..registry import get_action_definition
from .common import _hash_payload, _require_permission
from .reads import _expiry, _resource_refs, _side_effects

__all__ = [
    "_validate_source_ai_run", "create_proposal",
]


async def _validate_source_ai_run(
    session: AsyncSession,
    context: RequestContext,
    source_ai_run_id: str | None,
) -> None:
    if source_ai_run_id is None:
        return
    from ...models import AIRun

    run = await session.scalar(
        select(AIRun).where(
            AIRun.id == source_ai_run_id,
            AIRun.tenant_id == context.tenant_id,
        )
    )
    if run is None:
        raise NotFoundError("Source AI run not found")
    if run.status not in {"succeeded", "fallback"}:
        raise ConflictError("Only completed AI runs can source an action proposal")


async def create_proposal(
    session: AsyncSession,
    context: RequestContext,
    payload: ActionProposalCreate,
    idempotency_key: str,
    *,
    commit: bool = True,
) -> ActionProposal:
    _require_permission(context, Permission.ACTIONS_PROPOSE)
    if not idempotency_key.strip():
        raise InvalidRequestError("Idempotency-Key header is required")
    definition = get_action_definition(payload.action_type)
    _require_permission(context, definition.required_permission)
    normalized = definition.validate(payload.payload)
    normalized_payload = normalized.model_dump(mode="json", exclude_unset=True)
    request_digest = _hash_payload(definition.action_type, normalized_payload)
    existing = await session.scalar(
        select(ActionProposal).where(
            ActionProposal.tenant_id == context.tenant_id,
            ActionProposal.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_hash != request_digest:
            raise ConflictError("Idempotency-Key was reused for a different action proposal")
        return existing
    await _validate_source_ai_run(session, context, payload.source_ai_run_id)
    proposal = ActionProposal(
        tenant_id=context.tenant_id,
        idempotency_key=idempotency_key,
        request_hash=request_digest,
        action_type=definition.action_type,
        action_version=definition.version,
        required_permission=definition.required_permission.value,
        risk_level=definition.risk_level,
        requires_approval=definition.requires_approval,
        status="proposed",
        payload=normalized_payload,
        evidence_refs=payload.evidence_refs,
        affected_resources=payload.affected_resources or _resource_refs(
            definition.action_type, normalized_payload
        ),
        intended_changes=payload.intended_changes or normalized_payload,
        expected_side_effects=_side_effects(definition, payload.expected_side_effects),
        source_ai_run_id=payload.source_ai_run_id,
        requested_by=context.actor_id,
        expires_at=_expiry(payload.expires_at),
    )
    session.add(proposal)
    await session.flush()
    await record_audit(
        session,
        context,
        "action.proposal.created",
        "action_proposal",
        proposal.id,
        details={"action_type": proposal.action_type, "risk_level": proposal.risk_level},
    )
    await record_outbox_event(
        session,
        context,
        "action.proposal.created",
        "action_proposal",
        proposal.id,
        {"action_type": proposal.action_type, "status": proposal.status},
    )
    if commit:
        await session.commit()
        await session.refresh(proposal)
    return proposal
