from typing import Annotated

from fastapi import Header

from ...integrations import (
    create_external_write,
    list_record_links,
    list_sync_runs,
    sync_connection,
)
from ...schemas import (
    ExternalWriteCreate,
    ExternalWriteRead,
    IntegrationRecordLinkRead,
    IntegrationSyncRunRead,
)
from .base import ReadContext, SessionDependency, SyncContext, WriteContext, router

__all__ = [
    "create_external_write_endpoint", "list_record_links_endpoint", "list_sync_runs_endpoint",
    "sync_connection_endpoint",
]


@router.post(
    "/integrations/connections/{connection_id}/sync",
    response_model=IntegrationSyncRunRead,
    tags=["integrations"],
)
async def sync_connection_endpoint(
    connection_id: str,
    session: SessionDependency,
    context: SyncContext,
    mode: str = "incremental",
) -> IntegrationSyncRunRead:
    run = await sync_connection(session, context, connection_id, mode)
    return IntegrationSyncRunRead.model_validate(run)


@router.get(
    "/integrations/connections/{connection_id}/sync-runs",
    response_model=list[IntegrationSyncRunRead],
    tags=["integrations"],
)
async def list_sync_runs_endpoint(
    connection_id: str,
    session: SessionDependency,
    context: ReadContext,
) -> list[IntegrationSyncRunRead]:
    runs = await list_sync_runs(session, context, connection_id)
    return [IntegrationSyncRunRead.model_validate(run) for run in runs]


@router.get(
    "/integrations/connections/{connection_id}/links",
    response_model=list[IntegrationRecordLinkRead],
    tags=["integrations"],
)
async def list_record_links_endpoint(
    connection_id: str,
    session: SessionDependency,
    context: ReadContext,
) -> list[IntegrationRecordLinkRead]:
    links = await list_record_links(session, context, connection_id)
    return [IntegrationRecordLinkRead.model_validate(link) for link in links]


@router.post(
    "/integrations/connections/{connection_id}/writes",
    response_model=ExternalWriteRead,
    tags=["integrations"],
)
async def create_external_write_endpoint(
    connection_id: str,
    payload: ExternalWriteCreate,
    session: SessionDependency,
    context: WriteContext,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ExternalWriteRead:
    write = await create_external_write(
        session,
        context,
        connection_id,
        payload,
        idempotency_key or "",
    )
    return ExternalWriteRead.model_validate(write)
