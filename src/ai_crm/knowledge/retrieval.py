from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.deps import RequestContext
from ..audit import record_audit
from ..domain import InvalidRequestError
from ..models import KnowledgeChunk, KnowledgeContextAssembly, KnowledgeSource
from ..schemas import KnowledgeContextRequest
from .domain import (
    SOURCE_TYPES,
    ContextItem,
    ContextResult,
    KnowledgeHit,
    citation,
    freshness,
    source_visible,
    tokens,
)


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


async def assemble_context(
    session: AsyncSession,
    context: RequestContext,
    payload: KnowledgeContextRequest,
) -> ContextResult:
    hits, _ = await search_knowledge(
        session,
        context,
        query=payload.query,
        limit=min(payload.max_items * 5, 100),
        offset=0,
        customer_id=payload.customer_id,
        include_stale=payload.include_stale,
        require_ai_allowed=True,
        source_types=payload.source_types,
    )
    selected: list[ContextItem] = []
    item_ids: list[str] = []
    citations: list[dict[str, object]] = []
    used_chars = 0
    truncated = False
    for hit in hits:
        if len(selected) >= payload.max_items:
            truncated = True
            break
        remaining = payload.max_chars - used_chars
        if remaining <= 0:
            truncated = True
            break
        text = hit.chunk.content
        if len(text) > remaining:
            text = text[:remaining].rstrip()
            truncated = True
        if not text:
            continue
        item_citation = citation(hit.source, hit.chunk)
        selected.append(
            ContextItem(
                chunk_id=hit.chunk.id,
                text=text,
                title=hit.source.title,
                score=hit.score,
                freshness=hit.freshness,
                citation=item_citation,
            )
        )
        item_ids.append(hit.chunk.id)
        citations.append(item_citation)
        used_chars += len(text)
        if used_chars >= payload.max_chars:
            break

    assembly = KnowledgeContextAssembly(
        tenant_id=context.tenant_id,
        actor_id=context.actor_id,
        query=payload.query,
        request_scope={
            "customer_id": payload.customer_id,
            "workflow_id": payload.workflow_id,
            "task_id": payload.task_id,
            "action_type": payload.action_type,
            "source_types": payload.source_types,
            "include_stale": payload.include_stale,
        },
        item_ids=item_ids,
        citations=citations,
        used_chars=used_chars,
        max_items=payload.max_items,
        max_chars=payload.max_chars,
        truncated=truncated,
        insufficient_evidence=not selected,
    )
    session.add(assembly)
    await session.flush()
    await record_audit(
        session,
        context,
        "knowledge.context.assembled",
        "knowledge_context_assembly",
        assembly.id,
        details={
            "item_count": len(selected),
            "used_chars": used_chars,
            "insufficient_evidence": not selected,
        },
    )
    await session.commit()
    await session.refresh(assembly)
    return ContextResult(assembly=assembly, items=selected)
