from datetime import datetime

from fastapi import Query

from ...knowledge import (
    assemble_context,
    search_knowledge,
)
from ...schemas import (
    KnowledgeContextItem,
    KnowledgeContextRequest,
    KnowledgeContextResponse,
    KnowledgeSearchResponse,
    KnowledgeSearchResult,
)
from .base import ContextContext, ReadContext, SessionDependency, router

__all__ = [
    "assemble_context_endpoint", "search_endpoint",
]


@router.get(
    "/knowledge/search",
    response_model=KnowledgeSearchResponse,
    tags=["knowledge"],
)
async def search_endpoint(
    session: SessionDependency,
    context: ReadContext,
    q: str = Query(default="", max_length=500),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    source_type: str | None = None,
    source_record_id: str | None = None,
    customer_id: str | None = None,
    owner_id: str | None = None,
    source_status: str | None = None,
    effective_from: datetime | None = None,
    effective_to: datetime | None = None,
    include_archived: bool = False,
    include_stale: bool = True,
) -> KnowledgeSearchResponse:
    hits, next_offset = await search_knowledge(
        session,
        context,
        query=q.strip(),
        limit=limit,
        offset=offset,
        source_type=source_type,
        source_record_id=source_record_id,
        customer_id=customer_id,
        owner_id=owner_id,
        source_status=source_status,
        effective_from=effective_from,
        effective_to=effective_to,
        include_archived=include_archived,
        include_stale=include_stale,
    )
    items = [
        KnowledgeSearchResult(
            chunk_id=hit.chunk.id,
            text=hit.chunk.content,
            title=hit.source.title,
            score=hit.score,
            freshness=hit.freshness,
            source_id=hit.source.id,
            source_type=hit.source.source_type,
            source_record_id=hit.source.source_record_id,
            source_url=hit.source.source_url,
            source_version=hit.source.version,
            chunk_index=hit.chunk.chunk_index,
            owner_id=hit.source.owner_id,
            effective_at=hit.source.effective_at,
            fresh_until=hit.source.fresh_until,
            citation={
                "source_id": hit.source.id,
                "source_type": hit.source.source_type,
                "source_record_id": hit.source.source_record_id,
                "source_version": hit.source.version,
                "source_url": hit.source.source_url,
                "title": hit.source.title,
                "chunk_index": hit.chunk.chunk_index,
                "effective_at": (
                    hit.source.effective_at.isoformat() if hit.source.effective_at else None
                ),
                "fresh_until": (
                    hit.source.fresh_until.isoformat() if hit.source.fresh_until else None
                ),
            },
        )
        for hit in hits
    ]
    return KnowledgeSearchResponse(
        query=q.strip(),
        items=items,
        limit=limit,
        offset=offset,
        next_offset=next_offset,
        insufficient_evidence=not items,
        evidence_reason="No authorised indexed source matched the request" if not items else None,
    )


@router.post(
    "/knowledge/context",
    response_model=KnowledgeContextResponse,
    tags=["knowledge"],
)
async def assemble_context_endpoint(
    payload: KnowledgeContextRequest,
    session: SessionDependency,
    context: ContextContext,
) -> KnowledgeContextResponse:
    result = await assemble_context(session, context, payload)
    return KnowledgeContextResponse(
        assembly_id=result.assembly.id,
        query=result.assembly.query,
        items=[
            KnowledgeContextItem(
                chunk_id=item.chunk_id,
                text=item.text,
                title=item.title,
                score=item.score,
                freshness=item.freshness,
                citation=item.citation,
            )
            for item in result.items
        ],
        used_chars=result.assembly.used_chars,
        max_items=result.assembly.max_items,
        max_chars=result.assembly.max_chars,
        truncated=result.assembly.truncated,
        insufficient_evidence=result.assembly.insufficient_evidence,
    )
