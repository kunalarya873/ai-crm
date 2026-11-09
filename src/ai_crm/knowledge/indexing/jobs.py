from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import RequestContext
from ...audit import record_audit
from ...domain import NotFoundError
from ...models import KnowledgeIndexJob
from ..registry import get_source_for_tenant, queue_index_job_in_session

__all__ = [
    "get_index_job", "list_index_jobs", "queue_index_job",
]


async def queue_index_job(
    session: AsyncSession,
    context: RequestContext,
    source_id: str,
) -> KnowledgeIndexJob:
    source = await get_source_for_tenant(session, context, source_id)
    job = await queue_index_job_in_session(session, source)
    await record_audit(
        session,
        context,
        "knowledge.index.queued",
        "knowledge_index_job",
        job.id,
        details={"source_id": source.id, "source_version": source.version},
    )
    await session.commit()
    await session.refresh(job)
    return job


async def get_index_job(
    session: AsyncSession,
    context: RequestContext,
    job_id: str,
) -> KnowledgeIndexJob:
    job = await session.scalar(
        select(KnowledgeIndexJob).where(
            KnowledgeIndexJob.id == job_id,
            KnowledgeIndexJob.tenant_id == context.tenant_id,
        )
    )
    if job is None:
        raise NotFoundError("Knowledge index job not found")
    return job


async def list_index_jobs(
    session: AsyncSession,
    context: RequestContext,
    *,
    status: str | None = None,
) -> list[KnowledgeIndexJob]:
    statement = select(KnowledgeIndexJob).where(
        KnowledgeIndexJob.tenant_id == context.tenant_id
    )
    if status:
        statement = statement.where(KnowledgeIndexJob.status == status)
    result = await session.scalars(statement.order_by(KnowledgeIndexJob.created_at.desc()))
    return list(result)
