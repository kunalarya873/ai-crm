from fastapi import status

from ...integrations import (
    create_connection,
    list_connections,
    refresh_connection,
    set_connection_status,
    test_connection,
)
from ...schemas import IntegrationConnectionCreate, IntegrationConnectionRead
from .base import ManageContext, ReadContext, SessionDependency, router

__all__ = [
    "create_connection_endpoint", "disconnect_connection_endpoint", "list_connections_endpoint",
    "refresh_connection_endpoint", "revoke_connection_endpoint", "test_connection_endpoint",
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
    "/integrations/connections/{connection_id}/refresh",
    response_model=IntegrationConnectionRead,
    tags=["integrations"],
)
async def refresh_connection_endpoint(
    connection_id: str,
    session: SessionDependency,
    context: ManageContext,
) -> IntegrationConnectionRead:
    connection = await refresh_connection(session, context, connection_id)
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
