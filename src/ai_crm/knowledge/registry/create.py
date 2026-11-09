from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import RequestContext
from ...audit import record_audit, record_outbox_event
from ...domain import (
    ConflictError,
    InvalidRequestError,
)
from ...models import KnowledgeSource, utc_now
from ...schemas import KnowledgeSourceCreate
from ..domain import validate_source_fields

__all__ = [
    "create_source",
]


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
