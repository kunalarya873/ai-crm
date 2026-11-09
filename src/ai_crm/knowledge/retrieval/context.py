from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import RequestContext
from ...audit import record_audit
from ...models import KnowledgeContextAssembly
from ...schemas import KnowledgeContextRequest
from ..domain import ContextItem, ContextResult, citation
from .search import search_knowledge

__all__ = [
    "assemble_context",
]


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
