from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import RequestContext
from ...audit import record_audit, record_outbox_event
from ...domain import ConflictError, InvalidRequestError
from ...flags import require_capability
from ...models import WorkflowInstance, WorkflowTransition
from ...schemas import WorkflowStart
from ..domain import workflow_steps

__all__ = [
    "start_workflow",
]


async def start_workflow(
    session: AsyncSession,
    context: RequestContext,
    payload: WorkflowStart,
    idempotency_key: str,
) -> WorkflowInstance:
    await require_capability(session, context, "workflows", operation="workflow.start")
    if not idempotency_key.strip():
        raise InvalidRequestError("Idempotency-Key header is required")
    steps = workflow_steps(payload.workflow_key)
    existing = await session.scalar(
        select(WorkflowInstance).where(
            WorkflowInstance.tenant_id == context.tenant_id,
            WorkflowInstance.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if (
            existing.workflow_key != payload.workflow_key
            or existing.input_refs != payload.input_refs
        ):
            raise ConflictError("Idempotency-Key was reused for a different workflow")
        return existing
    workflow = WorkflowInstance(
        tenant_id=context.tenant_id,
        idempotency_key=idempotency_key,
        workflow_key=payload.workflow_key,
        owner_id=payload.owner_id or context.actor_id,
        steps=list(steps),
        input_refs=payload.input_refs,
        status="running",
    )
    session.add(workflow)
    await session.flush()
    session.add(
        WorkflowTransition(
            tenant_id=context.tenant_id,
            workflow_id=workflow.id,
            from_status="new",
            to_status="running",
            from_step=-1,
            to_step=0,
            actor_id=context.actor_id,
            reason="workflow_started",
        )
    )
    await record_audit(
        session,
        context,
        "workflow.started",
        "workflow_instance",
        workflow.id,
        details={"workflow_key": workflow.workflow_key},
    )
    await record_outbox_event(
        session,
        context,
        "workflow.started",
        "workflow_instance",
        workflow.id,
        {"workflow_key": workflow.workflow_key, "step": workflow.steps[0]},
    )
    await session.commit()
    await session.refresh(workflow)
    return workflow
