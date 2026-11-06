import hashlib
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.deps import RequestContext
from ..audit import record_audit, record_outbox_event
from ..config import settings
from ..domain import ConflictError, InvalidRequestError, NotFoundError
from ..models import KnowledgeChunk, KnowledgeIndexJob, utc_now
from .domain import chunk_content, tokens
from .registry import get_source_for_tenant, queue_index_job_in_session


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


async def run_index_job(
    session: AsyncSession,
    context: RequestContext,
    job_id: str,
) -> KnowledgeIndexJob:
    job = await get_index_job(session, context, job_id)
    source = await get_source_for_tenant(session, context, job.source_id)
    if job.status == "succeeded":
        return job
    if (
        job.status == "running"
        and job.lease_expires_at is not None
        and job.lease_expires_at > utc_now()
    ):
        raise ConflictError("Knowledge index job is already running")
    if source.version != job.source_version:
        job.status = "superseded"
        job.finished_at = utc_now()
        await session.commit()
        await session.refresh(job)
        return job

    job.status = "running"
    job.attempts += 1
    job.lease_owner = context.actor_id
    job.lease_expires_at = utc_now() + timedelta(seconds=settings.knowledge_lease_seconds)
    job.started_at = job.started_at or utc_now()
    job.failure_code = None
    job.failure_detail = None
    await session.commit()

    try:
        chunks = (
            chunk_content(source.content)
            if source.status == "active" and source.searchable
            else []
        )
        if source.status == "active" and source.searchable and not chunks:
            raise InvalidRequestError("Knowledge source has no indexable content")
        await session.execute(delete(KnowledgeChunk).where(KnowledgeChunk.source_id == source.id))
        for index, content in enumerate(chunks):
            session.add(
                KnowledgeChunk(
                    tenant_id=source.tenant_id,
                    source_id=source.id,
                    source_version=source.version,
                    chunk_index=index,
                    content=content,
                    content_hash=hashlib.sha256(content.encode()).hexdigest(),
                    token_count=len(tokens(content)),
                    status="published",
                )
            )
        job.status = "succeeded"
        job.indexed_chunks = len(chunks)
        job.finished_at = utc_now()
        job.lease_owner = None
        job.lease_expires_at = None
        await record_audit(
            session,
            context,
            "knowledge.index.succeeded",
            "knowledge_index_job",
            job.id,
            details={"indexed_chunks": len(chunks), "source_version": source.version},
        )
        await record_outbox_event(
            session,
            context,
            "knowledge.index.succeeded",
            "knowledge_index_job",
            job.id,
            {"indexed_chunks": len(chunks), "source_id": source.id},
        )
    except Exception as error:
        await session.rollback()
        job = await get_index_job(session, context, job_id)
        job.status = "failed"
        job.failure_code = "indexing_failed"
        job.failure_detail = str(error)[:500]
        job.finished_at = utc_now()
        job.lease_owner = None
        job.lease_expires_at = None
        await record_audit(
            session,
            context,
            "knowledge.index.failed",
            "knowledge_index_job",
            job.id,
            outcome="failed",
            reason=job.failure_code,
            details={"detail": job.failure_detail},
        )
    await session.commit()
    await session.refresh(job)
    return job
