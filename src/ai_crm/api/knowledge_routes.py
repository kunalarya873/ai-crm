from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.deps import RequestContext, require_permission
from ..db import get_session
from ..knowledge import (
    assemble_context,
    create_source,
    get_source_for_tenant,
    list_index_jobs,
    list_sources,
    queue_index_job,
    run_index_job,
    search_knowledge,
    update_source,
)
from ..permissions import Permission
from ..schemas import (
    KnowledgeContextItem,
    KnowledgeContextRequest,
    KnowledgeContextResponse,
    KnowledgeIndexJobRead,
    KnowledgeSearchResponse,
    KnowledgeSearchResult,
    KnowledgeSourceCreate,
    KnowledgeSourceRead,
    KnowledgeSourceUpdate,
)
from .routes import parse_if_match, set_etag

router = APIRouter()
SessionDependency = Annotated[AsyncSession, Depends(get_session)]
ReadContext = Annotated[
    RequestContext,
    Depends(require_permission(Permission.KNOWLEDGE_READ)),
]
ManageContext = Annotated[
    RequestContext,
    Depends(require_permission(Permission.KNOWLEDGE_MANAGE)),
]
ContextContext = Annotated[
    RequestContext,
    Depends(require_permission(Permission.KNOWLEDGE_CONTEXT)),
]


@router.post(
    "/knowledge/sources",
    response_model=KnowledgeSourceRead,
    status_code=status.HTTP_201_CREATED,
    tags=["knowledge"],
)
async def create_source_endpoint(
    payload: KnowledgeSourceCreate,
    response: Response,
    session: SessionDependency,
    context: ManageContext,
) -> KnowledgeSourceRead:
    source = await create_source(session, context, payload)
    set_etag(response, source.version)
    return KnowledgeSourceRead.model_validate(source)


@router.get(
    "/knowledge/sources",
    response_model=list[KnowledgeSourceRead],
    tags=["knowledge"],
)
async def list_sources_endpoint(
    session: SessionDependency,
    context: ReadContext,
    include_archived: bool = False,
    source_type: str | None = None,
) -> list[KnowledgeSourceRead]:
    sources = await list_sources(
        session,
        context,
        include_archived=include_archived,
        source_type=source_type,
    )
    return [KnowledgeSourceRead.model_validate(source) for source in sources]


@router.get(
    "/knowledge/sources/{source_id}",
    response_model=KnowledgeSourceRead,
    tags=["knowledge"],
)
async def get_source_endpoint(
    source_id: str,
    response: Response,
    session: SessionDependency,
    context: ReadContext,
) -> KnowledgeSourceRead:
    source = await get_source_for_tenant(
        session,
        context,
        source_id,
        require_visibility=True,
    )
    set_etag(response, source.version)
    return KnowledgeSourceRead.model_validate(source)


@router.patch(
    "/knowledge/sources/{source_id}",
    response_model=KnowledgeSourceRead,
    tags=["knowledge"],
)
async def update_source_endpoint(
    source_id: str,
    payload: KnowledgeSourceUpdate,
    response: Response,
    session: SessionDependency,
    context: ManageContext,
    if_match: Annotated[str | None, Header()] = None,
) -> KnowledgeSourceRead:
    source = await update_source(
        session,
        context,
        source_id,
        payload,
        parse_if_match(if_match),
    )
    set_etag(response, source.version)
    return KnowledgeSourceRead.model_validate(source)


@router.post(
    "/knowledge/sources/{source_id}/index",
    response_model=KnowledgeIndexJobRead,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["knowledge"],
)
async def queue_index_endpoint(
    source_id: str,
    session: SessionDependency,
    context: ManageContext,
) -> KnowledgeIndexJobRead:
    job = await queue_index_job(session, context, source_id)
    return KnowledgeIndexJobRead.model_validate(job)


@router.get(
    "/knowledge/index-jobs",
    response_model=list[KnowledgeIndexJobRead],
    tags=["knowledge"],
)
async def list_index_jobs_endpoint(
    session: SessionDependency,
    context: ManageContext,
    job_status: str | None = Query(default=None, alias="status"),
) -> list[KnowledgeIndexJobRead]:
    jobs = await list_index_jobs(session, context, status=job_status)
    return [KnowledgeIndexJobRead.model_validate(job) for job in jobs]


@router.post(
    "/knowledge/index-jobs/{job_id}/run",
    response_model=KnowledgeIndexJobRead,
    tags=["knowledge"],
)
async def run_index_job_endpoint(
    job_id: str,
    session: SessionDependency,
    context: ManageContext,
) -> KnowledgeIndexJobRead:
    job = await run_index_job(session, context, job_id)
    return KnowledgeIndexJobRead.model_validate(job)


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
