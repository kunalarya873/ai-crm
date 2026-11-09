from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import RequestContext
from ...domain import (
    InvalidRequestError,
    NotFoundError,
)
from ...models import KnowledgeIndexJob, KnowledgeSource
from ..domain import SOURCE_TYPES, source_visible

__all__ = [
    "get_source_for_tenant", "list_sources", "queue_index_job_in_session",
]


async def get_source_for_tenant(
    session: AsyncSession,
    context: RequestContext,
    source_id: str,
    *,
    require_visibility: bool = False,
) -> KnowledgeSource:
    source = await session.scalar(
        select(KnowledgeSource).where(
            KnowledgeSource.id == source_id,
            KnowledgeSource.tenant_id == context.tenant_id,
        )
    )
    if source is None or (require_visibility and not source_visible(source, context)):
        raise NotFoundError("Knowledge source not found")
    return source


async def list_sources(
    session: AsyncSession,
    context: RequestContext,
    *,
    include_archived: bool = False,
    source_type: str | None = None,
) -> list[KnowledgeSource]:
    statement = select(KnowledgeSource).where(KnowledgeSource.tenant_id == context.tenant_id)
    if not include_archived:
        statement = statement.where(KnowledgeSource.archived_at.is_(None))
    if source_type is not None:
        if source_type not in SOURCE_TYPES:
            raise InvalidRequestError(f"Unsupported knowledge source type: {source_type}")
        statement = statement.where(KnowledgeSource.source_type == source_type)
    result = await session.scalars(statement.order_by(KnowledgeSource.updated_at.desc()))
    return [source for source in result if source_visible(source, context)]


async def queue_index_job_in_session(
    session: AsyncSession,
    source: KnowledgeSource,
) -> KnowledgeIndexJob:
    job = await session.scalar(
        select(KnowledgeIndexJob).where(
            KnowledgeIndexJob.source_id == source.id,
            KnowledgeIndexJob.source_version == source.version,
        )
    )
    if job is None:
        job = KnowledgeIndexJob(
            tenant_id=source.tenant_id,
            source_id=source.id,
            source_version=source.version,
            status="queued",
        )
        session.add(job)
        await session.flush()
    elif job.status == "failed":
        job.status = "queued"
        job.failure_code = None
        job.failure_detail = None
        job.finished_at = None
        job.lease_owner = None
        job.lease_expires_at = None
    return job
