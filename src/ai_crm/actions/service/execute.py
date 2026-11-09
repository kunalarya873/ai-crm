from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import RequestContext
from ...domain import ConflictError, InvalidTransitionError
from ...models import ActionExecution, utc_now
from ...permissions import Permission
from ...schemas import ActionRecoveryRequest
from ..registry import get_action_definition
from .common import _check_version, _ensure_not_expired, _require_permission
from .lifecycle import _proposal_event
from .reads import get_execution, get_proposal
from .run import _run_execution

__all__ = [
    "execute_proposal", "retry_execution",
]


async def execute_proposal(
    session: AsyncSession,
    context: RequestContext,
    proposal_id: str,
    expected_version: int | None,
) -> ActionExecution:
    _require_permission(context, Permission.ACTIONS_EXECUTE)
    proposal = await get_proposal(session, context, proposal_id)
    _check_version(proposal, expected_version)
    _ensure_not_expired(proposal)
    if proposal.status != "approved":
        raise InvalidTransitionError(f"Only approved proposals can execute: {proposal.status}")
    definition = get_action_definition(proposal.action_type)
    _require_permission(context, definition.required_permission)
    definition.validate(proposal.payload)
    existing = await session.scalar(
        select(ActionExecution).where(
            ActionExecution.tenant_id == context.tenant_id,
            ActionExecution.action_proposal_id == proposal.id,
        )
    )
    if existing is not None:
        if existing.status == "succeeded":
            return existing
        raise ConflictError(f"Action execution already exists in state {existing.status}")
    execution = ActionExecution(
        tenant_id=context.tenant_id,
        action_proposal_id=proposal.id,
        idempotency_key=f"action:{proposal.id}",
        action_type=proposal.action_type,
        request_hash=proposal.request_hash,
        status="executing",
        attempts=1,
        started_at=utc_now(),
    )
    proposal.status = "executing"
    proposal.version += 1
    proposal.updated_at = utc_now()
    session.add(execution)
    await _proposal_event(session, context, proposal, "action.execution.started", None)
    await session.commit()
    await session.refresh(execution)
    return await _run_execution(session, context, proposal.id, execution.id)


async def retry_execution(
    session: AsyncSession,
    context: RequestContext,
    execution_id: str,
    payload: ActionRecoveryRequest,
) -> ActionExecution:
    _require_permission(context, Permission.ACTIONS_RECOVER)
    execution = await get_execution(session, context, execution_id)
    if execution.status == "uncertain":
        raise ConflictError("Reconcile an uncertain external outcome before retrying")
    if execution.status not in {"failed", "recoverable"}:
        raise ConflictError(f"Only failed or recoverable executions can retry: {execution.status}")
    proposal = await get_proposal(session, context, execution.action_proposal_id)
    _ensure_not_expired(proposal)
    definition = get_action_definition(proposal.action_type)
    _require_permission(context, definition.required_permission)
    if execution.attempts >= definition.max_attempts:
        raise ConflictError("Action execution has exhausted its retry limit")
    proposal.status = "approved"
    proposal.version += 1
    proposal.updated_at = utc_now()
    execution.status = "executing"
    execution.attempts += 1
    execution.operator_note = payload.operator_note
    execution.error_code = None
    execution.error_detail = None
    execution.uncertain_outcome = False
    execution.started_at = utc_now()
    await _proposal_event(
        session,
        context,
        proposal,
        "action.execution.retried",
        payload.operator_note,
    )
    await session.commit()
    return await _run_execution(session, context, proposal.id, execution.id)
