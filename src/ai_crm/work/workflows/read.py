from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import RequestContext
from ...domain import NotFoundError
from ...models import WorkflowInstance

__all__ = [
    "get_workflow", "list_workflows",
]


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
