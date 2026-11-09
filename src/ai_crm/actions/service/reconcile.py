from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import RequestContext
from ...audit import record_audit
from ...domain import ConflictError
from ...models import ActionExecution, ExternalWrite, utc_now
from ...permissions import Permission
from ...schemas import ActionRecoveryRequest
from .common import _require_permission
from .reads import get_execution, get_proposal

__all__ = [
    "reconcile_execution",
]


async def reconcile_execution(
    session: AsyncSession,
    context: RequestContext,
    execution_id: str,
    payload: ActionRecoveryRequest,
) -> ActionExecution:
    _require_permission(context, Permission.ACTIONS_RECOVER)
    execution = await get_execution(session, context, execution_id)
    if execution.status != "uncertain":
        raise ConflictError("Only uncertain executions can be reconciled")
    write = await session.scalar(
        select(ExternalWrite).where(
            ExternalWrite.idempotency_key == execution.idempotency_key,
        )
    )
    if write is None:
        raise ConflictError("External outcome is not available for reconciliation")
    if write.status != "succeeded":
        execution.operator_note = payload.operator_note
        await session.commit()
        raise ConflictError("External outcome is still unresolved")
    proposal = await get_proposal(session, context, execution.action_proposal_id)
    execution.status = "succeeded"
    execution.result = {
        "external_write_id": write.id,
        "response_metadata": write.response_metadata,
        "reconciled": True,
    }
    execution.provider_request_id = write.provider_request_id
    execution.uncertain_outcome = False
    execution.operator_note = payload.operator_note
    execution.completed_at = utc_now()
    proposal.status = "succeeded"
    proposal.version += 1
    proposal.updated_at = utc_now()
    await record_audit(
        session,
        context,
        "action.execution.reconciled",
        "action_execution",
        execution.id,
        details={"proposal_id": proposal.id, "external_write_id": write.id},
    )
    await session.commit()
    await session.refresh(execution)
    return execution
