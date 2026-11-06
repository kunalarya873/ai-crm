from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.deps import RequestContext
from ..audit import record_audit, record_outbox_event
from ..domain import ConflictError, InvalidRequestError, NotFoundError
from ..models import WorkflowInstance, WorkflowTransition, utc_now
from ..schemas import WorkflowAdvance, WorkflowStart
from .domain import workflow_steps


async def get_workflow(
    session: AsyncSession,
    context: RequestContext,
    workflow_id: str,
) -> WorkflowInstance:
    workflow = await session.scalar(
        select(WorkflowInstance).where(
            WorkflowInstance.id == workflow_id,
            WorkflowInstance.tenant_id == context.tenant_id,
        )
    )
    if workflow is None:
        raise NotFoundError("Workflow instance not found")
    return workflow


async def start_workflow(
    session: AsyncSession,
    context: RequestContext,
    payload: WorkflowStart,
    idempotency_key: str,
) -> WorkflowInstance:
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


async def list_workflows(
    session: AsyncSession,
    context: RequestContext,
    *,
    limit: int,
    offset: int,
    workflow_status: str | None = None,
    owner_id: str | None = None,
) -> list[WorkflowInstance]:
    statement = select(WorkflowInstance).where(WorkflowInstance.tenant_id == context.tenant_id)
    if workflow_status:
        statement = statement.where(WorkflowInstance.status == workflow_status)
    if owner_id:
        statement = statement.where(WorkflowInstance.owner_id == owner_id)
    result = await session.scalars(
        statement.order_by(WorkflowInstance.updated_at.desc()).offset(offset).limit(limit)
    )
    return list(result)


async def advance_workflow(
    session: AsyncSession,
    context: RequestContext,
    workflow_id: str,
    payload: WorkflowAdvance,
    expected_version: int | None,
) -> WorkflowInstance:
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


async def resume_workflow(
    session: AsyncSession,
    context: RequestContext,
    workflow_id: str,
    expected_version: int | None,
) -> WorkflowInstance:
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
