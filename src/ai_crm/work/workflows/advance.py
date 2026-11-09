from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import RequestContext
from ...audit import record_audit, record_outbox_event
from ...domain import ConflictError, InvalidRequestError
from ...flags import require_capability
from ...models import WorkflowInstance, WorkflowTransition, utc_now
from ...schemas import WorkflowAdvance
from .read import get_workflow
from .resume import _transition_workflow

__all__ = [
    "advance_workflow",
]


async def advance_workflow(
    session: AsyncSession,
    context: RequestContext,
    workflow_id: str,
    payload: WorkflowAdvance,
    expected_version: int | None,
) -> WorkflowInstance:
    await require_capability(session, context, "workflows", operation="workflow.advance")
    if expected_version is None:
        raise InvalidRequestError("If-Match header is required")
    workflow = await get_workflow(session, context, workflow_id)
    if workflow.version != expected_version:
        raise ConflictError("record_version_conflict")
    if workflow.status != "running":
        raise ConflictError(f"Workflow is not running: {workflow.status}")
    if workflow.current_step >= len(workflow.steps):
        raise ConflictError("Workflow has no remaining steps")
    current_step = workflow.steps[workflow.current_step]
    if current_step == "await_approval" and payload.approved is not True:
        workflow.status = "paused"
        await _transition_workflow(
            session,
            context,
            workflow,
            from_status="running",
            to_status="paused",
            from_step=workflow.current_step,
            to_step=workflow.current_step,
            reason=payload.reason or "approval_required",
        )
        workflow.waiting_for = "approval"
        workflow.version = expected_version + 1
        await session.commit()
        await session.refresh(workflow)
        return workflow
    if payload.output:
        workflow.outputs = {**workflow.outputs, current_step: payload.output}
    next_step = workflow.current_step + 1
    previous_step = workflow.current_step
    previous_status = workflow.status
    workflow.current_step = next_step
    workflow.version = expected_version + 1
    workflow.waiting_for = None
    if next_step >= len(workflow.steps):
        workflow.status = "completed"
        workflow.completed_at = utc_now()
    session.add(
        WorkflowTransition(
            tenant_id=context.tenant_id,
            workflow_id=workflow.id,
            from_status=previous_status,
            to_status=workflow.status,
            from_step=previous_step,
            to_step=next_step,
            actor_id=context.actor_id,
            reason=payload.reason,
        )
    )
    await record_audit(
        session,
        context,
        "workflow.advanced",
        "workflow_instance",
        workflow.id,
        details={"from_step": previous_step, "to_step": next_step, "status": workflow.status},
    )
    await record_outbox_event(
        session,
        context,
        "workflow.advanced",
        "workflow_instance",
        workflow.id,
        {"step": next_step, "status": workflow.status},
    )
    await session.commit()
    await session.refresh(workflow)
    return workflow
