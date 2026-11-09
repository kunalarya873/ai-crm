from typing import Annotated

from fastapi import Header, Response, status

from ...knowledge import (
    create_source,
    get_source_for_tenant,
    list_sources,
    update_source,
)
from ...schemas import (
    KnowledgeSourceCreate,
    KnowledgeSourceRead,
    KnowledgeSourceUpdate,
)
from ..routes import parse_if_match, set_etag
from .base import ManageContext, ReadContext, SessionDependency, router

__all__ = [
    "create_source_endpoint", "get_source_endpoint", "list_sources_endpoint",
    "update_source_endpoint",
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
