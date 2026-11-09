from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import RequestContext
from ...domain import InvalidRequestError
from ...models import KnowledgeChunk, KnowledgeSource
from ..domain import (
    SOURCE_TYPES,
    KnowledgeHit,
    freshness,
    source_visible,
    tokens,
)

__all__ = [
    "search_knowledge",
]


async def search_knowledge(
    session: AsyncSession,
    context: RequestContext,
    *,
    query: str,
    limit: int,
    offset: int,
    source_type: str | None = None,
    source_record_id: str | None = None,
    customer_id: str | None = None,
    owner_id: str | None = None,
    source_status: str | None = None,
    effective_from: datetime | None = None,
    effective_to: datetime | None = None,
    include_archived: bool = False,
    include_stale: bool = True,
    require_ai_allowed: bool = False,
    source_types: list[str] | None = None,
) -> tuple[list[KnowledgeHit], int | None]:
    requested_types = source_types or ([source_type] if source_type else [])
    invalid_types = [item for item in requested_types if item not in SOURCE_TYPES]
    if invalid_types:
        raise InvalidRequestError(f"Unsupported knowledge source type: {invalid_types[0]}")
    statement = (
        select(KnowledgeChunk, KnowledgeSource)
        .join(KnowledgeSource, KnowledgeSource.id == KnowledgeChunk.source_id)
        .where(
            KnowledgeChunk.tenant_id == context.tenant_id,
            KnowledgeChunk.status == "published",
            KnowledgeChunk.source_version == KnowledgeSource.version,
            KnowledgeSource.searchable.is_(True),
        )
    )
    if not include_archived:
        statement = statement.where(KnowledgeSource.status == "active")
    if source_status:
        statement = statement.where(KnowledgeSource.status == source_status)
    if requested_types:
        statement = statement.where(KnowledgeSource.source_type.in_(requested_types))
    if source_record_id:
        statement = statement.where(KnowledgeSource.source_record_id == source_record_id)
    if customer_id:
        statement = statement.where(KnowledgeSource.customer_id == customer_id)
    if owner_id:
        statement = statement.where(KnowledgeSource.owner_id == owner_id)
    if effective_from:
        statement = statement.where(KnowledgeSource.effective_at >= effective_from)
    if effective_to:
        statement = statement.where(KnowledgeSource.effective_at <= effective_to)

    rows = (await session.execute(statement)).all()
    query_tokens = tokens(query)
    phrase = " ".join(query_tokens)
    matches: list[KnowledgeHit] = []
    for chunk, source in rows:
        if not source_visible(source, context):
            continue
        if require_ai_allowed and not source.ai_allowed:
            continue
        source_freshness = freshness(source)
        if source_freshness == "stale" and not include_stale:
            continue
        searchable_text = f"{source.title} {chunk.content}".casefold()
        if query_tokens:
            term_counts = {token: searchable_text.count(token) for token in query_tokens}
            if not any(term_counts.values()):
                continue
            score = sum(term_counts.values()) / len(query_tokens)
            if phrase and phrase in searchable_text:
                score += 0.25
            if source.title.casefold().find(phrase) >= 0:
                score += 0.5
        else:
            score = 0.0
        matches.append(KnowledgeHit(chunk, source, score, source_freshness))

    matches.sort(
        key=lambda item: (-item.score, item.source.id, item.chunk.chunk_index, item.chunk.id)
    )
    page = matches[offset : offset + limit]
    next_offset = offset + limit if offset + limit < len(matches) else None
    return page, next_offset
