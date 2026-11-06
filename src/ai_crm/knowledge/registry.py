from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.deps import RequestContext
from ..audit import record_audit, record_outbox_event
from ..domain import (
    ConflictError,
    InvalidRequestError,
    NotFoundError,
    PreconditionRequiredError,
    VersionConflictError,
)
from ..models import KnowledgeIndexJob, KnowledgeSource, utc_now
from ..schemas import KnowledgeSourceCreate, KnowledgeSourceUpdate
from .domain import SOURCE_TYPES, source_visible, validate_source_fields


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


async def create_source(
    session: AsyncSession,
    context: RequestContext,
    payload: KnowledgeSourceCreate,
) -> KnowledgeSource:
    validate_source_fields(payload.source_type, payload.visibility, payload.sensitivity)
    if payload.visibility == "restricted" and not payload.allowed_user_ids:
        raise InvalidRequestError("Restricted knowledge sources require allowed_user_ids")
    existing = await session.scalar(
        select(KnowledgeSource).where(
            KnowledgeSource.tenant_id == context.tenant_id,
            KnowledgeSource.source_type == payload.source_type,
            KnowledgeSource.source_record_id == payload.source_record_id,
        )
    )
    if existing is not None:
        raise ConflictError("This knowledge source is already registered")
    source = KnowledgeSource(
        tenant_id=context.tenant_id,
        source_type=payload.source_type,
        source_record_id=payload.source_record_id,
        title=payload.title,
        content=payload.content,
        source_url=payload.source_url,
        owner_id=payload.owner_id or (context.actor_id if payload.visibility == "owner" else None),
        visibility=payload.visibility,
        allowed_user_ids=payload.allowed_user_ids,
        customer_id=payload.customer_id,
        searchable=payload.searchable,
        ai_allowed=payload.ai_allowed,
        sensitivity=payload.sensitivity,
        effective_at=payload.effective_at,
        fresh_until=payload.fresh_until,
        source_updated_at=utc_now(),
    )
    session.add(source)
    await session.flush()
    await record_audit(
        session,
        context,
        "knowledge.source.created",
        "knowledge_source",
        source.id,
        details={"source_type": source.source_type, "version": source.version},
    )
    await record_outbox_event(
        session,
        context,
        "knowledge.source.created",
        "knowledge_source",
        source.id,
        {"source_type": source.source_type, "version": source.version},
    )
    await session.commit()
    await session.refresh(source)
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


async def update_source(
    session: AsyncSession,
    context: RequestContext,
    source_id: str,
    payload: KnowledgeSourceUpdate,
    expected_version: int | None,
) -> KnowledgeSource:
    if expected_version is None:
        raise PreconditionRequiredError("If-Match header is required")
    if expected_version < 1:
        raise InvalidRequestError("If-Match must contain a positive integer version")
    source = await get_source_for_tenant(session, context, source_id)
    if source.version != expected_version:
        raise VersionConflictError("record_version_conflict")
    changes = payload.model_dump(exclude_unset=True)
    archived = changes.pop("archived", None)
    if not changes and archived is None:
        raise InvalidRequestError("At least one field is required")
    visibility = changes.get("visibility", source.visibility)
    sensitivity = changes.get("sensitivity", source.sensitivity)
    validate_source_fields(source.source_type, visibility, sensitivity)
    if visibility == "restricted" and not changes.get(
        "allowed_user_ids", source.allowed_user_ids
    ):
        raise InvalidRequestError("Restricted knowledge sources require allowed_user_ids")
    for key, value in changes.items():
        setattr(source, key, value)
    if visibility == "owner" and source.owner_id is None:
        source.owner_id = context.actor_id
    if archived is not None:
        source.archived_at = utc_now() if archived else None
        source.status = "archived" if archived else "active"
        source.searchable = not archived
    source.version = expected_version + 1
    source.source_updated_at = utc_now()
    await session.flush()
    job = await queue_index_job_in_session(session, source)
    await record_audit(
        session,
        context,
        "knowledge.source.updated",
        "knowledge_source",
        source.id,
        details={"version": source.version, "index_job_id": job.id},
    )
    await record_outbox_event(
        session,
        context,
        "knowledge.source.updated",
        "knowledge_source",
        source.id,
        {"version": source.version, "index_job_id": job.id},
    )
    await session.commit()
    await session.refresh(source)
    return source


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
