from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import RequestContext
from ...audit import record_audit, record_outbox_event
from ...domain import DomainError
from ...integrations import ConnectorProviderError
from ...models import ActionExecution, utc_now
from ..registry import get_action_definition
from .common import _error_code
from .dispatch import _execute_effect
from .reads import get_execution, get_proposal

__all__ = [
    "_run_execution",
]


async def _run_execution(
    session: AsyncSession,
    context: RequestContext,
    proposal_id: str,
    execution_id: str,
) -> ActionExecution:
    proposal = await get_proposal(session, context, proposal_id)
    execution = await get_execution(session, context, execution_id)
    definition = get_action_definition(proposal.action_type)
    try:
        result = await _execute_effect(session, context, definition, proposal.payload, execution)
        execution.status = "succeeded"
        execution.result = result
        execution.completed_at = utc_now()
        proposal.status = "succeeded"
        proposal.version += 1
        proposal.updated_at = utc_now()
        proposal.last_error_code = None
        proposal.last_error_detail = None
        await record_audit(
            session,
            context,
            "action.execution.succeeded",
            "action_execution",
            execution.id,
            details={"proposal_id": proposal.id, "action_type": proposal.action_type},
        )
        await record_outbox_event(
            session,
            context,
            "action.execution.succeeded",
            "action_execution",
            execution.id,
            {"proposal_id": proposal.id, "action_type": proposal.action_type},
        )
    except ConnectorProviderError as error:
        uncertain = error.code in {"uncertain", "timeout", "provider_timeout"}
        execution.status = "uncertain" if uncertain else "recoverable"
        execution.uncertain_outcome = uncertain
        execution.error_code = error.code
        execution.error_detail = str(error)[:500]
        proposal.status = "recoverable" if uncertain else "failed"
        proposal.last_error_code = error.code
        proposal.last_error_detail = str(error)[:500]
        proposal.version += 1
        proposal.updated_at = utc_now()
        await record_audit(
            session,
            context,
            "action.execution.recoverable" if uncertain else "action.execution.failed",
            "action_execution",
            execution.id,
            outcome="failed",
            reason=error.code,
            details={"proposal_id": proposal.id, "uncertain": uncertain},
        )
    except (DomainError, ValueError) as error:
        execution.status = "failed"
        execution.error_code = _error_code(error)
        execution.error_detail = str(error)[:500]
        proposal.status = "failed"
        proposal.last_error_code = execution.error_code
        proposal.last_error_detail = execution.error_detail
        proposal.version += 1
        proposal.updated_at = utc_now()
        await record_audit(
            session,
            context,
            "action.execution.failed",
            "action_execution",
            execution.id,
            outcome="failed",
            reason=execution.error_code,
            details={"proposal_id": proposal.id},
        )
    execution.updated_at = utc_now()
    await session.commit()
    await session.refresh(execution)
    return execution
