from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import RequestContext
from ...domain import NotFoundError
from ...models import DurableJob

__all__ = [
    "get_job", "list_jobs",
]


async def get_job(
    session: AsyncSession,
    context: RequestContext,
    job_id: str,
) -> DurableJob:
    job = await session.scalar(
        select(DurableJob).where(
            DurableJob.id == job_id,
            DurableJob.tenant_id == context.tenant_id,
        )
    )
    if job is None:
        raise NotFoundError("Job not found")
    return job


async def list_jobs(
    session: AsyncSession,
    context: RequestContext,
    *,
    limit: int,
    offset: int,
    queue: str | None = None,
    job_status: str | None = None,
) -> list[DurableJob]:
    statement = select(DurableJob).where(DurableJob.tenant_id == context.tenant_id)
    if queue:
        statement = statement.where(DurableJob.queue == queue)
    if job_status:
        statement = statement.where(DurableJob.status == job_status)
    result = await session.scalars(
        statement.order_by(DurableJob.created_at.desc()).offset(offset).limit(limit)
    )
    return list(result)
