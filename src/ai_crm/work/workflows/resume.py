from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import RequestContext
from ...audit import record_audit
from ...domain import ConflictError, InvalidRequestError
from ...flags import require_capability
from ...models import WorkflowInstance, WorkflowTransition
from .read import get_workflow

__all__ = [
    "_transition_workflow", "resume_workflow",
]


async def resume_workflow(
    session: AsyncSession,
    context: RequestContext,
    workflow_id: str,
    expected_version: int | None,
) -> WorkflowInstance:
    await require_capability(session, context, "workflows", operation="workflow.resume")
    if expected_version is None:
        raise InvalidRequestError("If-Match header is required")
    workflow = await get_workflow(session, context, workflow_id)
    if workflow.version != expected_version:
        raise ConflictError("record_version_conflict")
    if workflow.status != "paused":
        raise ConflictError("Only paused workflows can be resumed")
    previous_status = workflow.status
    workflow.status = "running"
    workflow.waiting_for = None
    workflow.version = expected_version + 1
    session.add(
        WorkflowTransition(
            tenant_id=context.tenant_id,
            workflow_id=workflow.id,
            from_status=previous_status,
            to_status=workflow.status,
            from_step=workflow.current_step,
            to_step=workflow.current_step,
            actor_id=context.actor_id,
            reason="workflow_resumed",
        )
    )
    await record_audit(session, context, "workflow.resumed", "workflow_instance", workflow.id)
    await session.commit()
    await session.refresh(workflow)
    return workflow


async def _transition_workflow(
    session: AsyncSession,
    context: RequestContext,
    workflow: WorkflowInstance,
    *,
    from_status: str,
    to_status: str,
    from_step: int,
    to_step: int,
    reason: str,
) -> None:
    session.add(
        WorkflowTransition(
            tenant_id=context.tenant_id,
            workflow_id=workflow.id,
            from_status=from_status,
            to_status=to_status,
            from_step=from_step,
            to_step=to_step,
            actor_id=context.actor_id,
            reason=reason,
        )
    )
    await record_audit(
        session,
        context,
        "workflow.paused",
        "workflow_instance",
        workflow.id,
        details={"waiting_for": "approval"},
    )
