from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.deps import RequestContext, require_permission
from ..db import get_session
from ..integrations import (
    create_connection,
    create_external_write,
    ingest_webhook,
    list_connections,
    list_record_links,
    list_sync_runs,
    set_connection_status,
    sync_connection,
    test_connection,
)
from ..permissions import Permission
from ..schemas import (
    ExternalWriteCreate,
    ExternalWriteRead,
    IntegrationConnectionCreate,
    IntegrationConnectionRead,
    IntegrationRecordLinkRead,
    IntegrationSyncRunRead,
    WebhookAccepted,
)

router = APIRouter()
SessionDependency = Annotated[AsyncSession, Depends(get_session)]
ReadContext = Annotated[
    RequestContext,
    Depends(require_permission(Permission.INTEGRATIONS_READ)),
]
ManageContext = Annotated[
    RequestContext,
    Depends(require_permission(Permission.INTEGRATIONS_MANAGE)),
]
SyncContext = Annotated[
    RequestContext,
    Depends(require_permission(Permission.INTEGRATIONS_SYNC)),
]
WriteContext = Annotated[
    RequestContext,
    Depends(require_permission(Permission.INTEGRATIONS_WRITE)),
]


@router.post(
    "/integrations/connections",
    response_model=IntegrationConnectionRead,
    status_code=status.HTTP_201_CREATED,
    tags=["integrations"],
)
async def create_connection_endpoint(
    payload: IntegrationConnectionCreate,
    session: SessionDependency,
    context: ManageContext,
) -> IntegrationConnectionRead:
    connection = await create_connection(session, context, payload)
    return IntegrationConnectionRead.model_validate(connection)


@router.get(
    "/integrations/connections",
    response_model=list[IntegrationConnectionRead],
    tags=["integrations"],
)
async def list_connections_endpoint(
    session: SessionDependency,
    context: ReadContext,
) -> list[IntegrationConnectionRead]:
    connections = await list_connections(session, context)
    return [IntegrationConnectionRead.model_validate(connection) for connection in connections]


@router.post(
    "/integrations/connections/{connection_id}/test",
    response_model=IntegrationConnectionRead,
    tags=["integrations"],
)
async def test_connection_endpoint(
    connection_id: str,
    session: SessionDependency,
    context: ManageContext,
) -> IntegrationConnectionRead:
    connection = await test_connection(session, context, connection_id)
    return IntegrationConnectionRead.model_validate(connection)


@router.post(
    "/integrations/connections/{connection_id}/disconnect",
    response_model=IntegrationConnectionRead,
    tags=["integrations"],
)
async def disconnect_connection_endpoint(
    connection_id: str,
    session: SessionDependency,
    context: ManageContext,
) -> IntegrationConnectionRead:
    connection = await set_connection_status(session, context, connection_id, "disconnected")
    return IntegrationConnectionRead.model_validate(connection)


@router.post(
    "/integrations/connections/{connection_id}/revoke",
    response_model=IntegrationConnectionRead,
    tags=["integrations"],
)
async def revoke_connection_endpoint(
    connection_id: str,
    session: SessionDependency,
    context: ManageContext,
) -> IntegrationConnectionRead:
    connection = await set_connection_status(session, context, connection_id, "revoked")
    return IntegrationConnectionRead.model_validate(connection)


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


@router.post(
    "/integrations/webhooks/{provider_key}",
    response_model=WebhookAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["integration-webhooks"],
)
async def receive_webhook_endpoint(
    provider_key: str,
    request: Request,
    session: SessionDependency,
    external_account_id: Annotated[str | None, Header(alias="X-Integration-Account")] = None,
    signature: Annotated[str | None, Header(alias="X-Webhook-Signature")] = None,
) -> WebhookAccepted:
    raw_body = await request.body()
    event = await ingest_webhook(
        session,
        provider_key,
        external_account_id or "",
        signature or "",
        raw_body,
    )
    return WebhookAccepted(
        id=event.id,
        provider_event_id=event.provider_event_id,
        status=event.status,
    )
