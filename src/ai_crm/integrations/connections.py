from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.deps import RequestContext
from ..audit import record_audit, record_outbox_event
from ..domain import ConflictError, InvalidTransitionError, NotFoundError
from ..flags import require_capability
from ..models import IntegrationConnection, utc_now
from ..schemas import IntegrationConnectionCreate
from .fixture import get_connector

__all__ = [
    "create_connection", "get_connection", "list_connections", "test_connection",
]


async def create_connection(
    session: AsyncSession,
    context: RequestContext,
    payload: IntegrationConnectionCreate,
) -> IntegrationConnection:
    get_connector(payload.provider_key)
    existing = await session.scalar(
        select(IntegrationConnection).where(
            IntegrationConnection.provider_key == payload.provider_key,
            IntegrationConnection.external_account_id == payload.external_account_id,
        )
    )
    if existing is not None:
        raise ConflictError("This external account is already connected")
    connection = IntegrationConnection(
        tenant_id=context.tenant_id,
        provider_key=payload.provider_key,
        external_account_id=payload.external_account_id,
        scopes=payload.scopes,
        secret_ref=payload.secret_ref,
        configuration=payload.configuration,
    )
    session.add(connection)
    await session.flush()
    await record_audit(
        session,
        context,
        "integration.connection.created",
        "integration_connection",
        connection.id,
        details={"provider_key": connection.provider_key},
    )
    await record_outbox_event(
        session,
        context,
        "integration.connection.created",
        "integration_connection",
        connection.id,
        {"provider_key": connection.provider_key},
    )
    await session.commit()
    await session.refresh(connection)
    return connection


async def get_connection(
    session: AsyncSession,
    context: RequestContext,
    connection_id: str,
) -> IntegrationConnection:
    connection = await session.scalar(
        select(IntegrationConnection).where(
            IntegrationConnection.id == connection_id,
            IntegrationConnection.tenant_id == context.tenant_id,
        )
    )
    if connection is None:
        raise NotFoundError("Integration connection not found")
    return connection


async def list_connections(
    session: AsyncSession,
    context: RequestContext,
) -> list[IntegrationConnection]:
    result = await session.scalars(
        select(IntegrationConnection)
        .where(IntegrationConnection.tenant_id == context.tenant_id)
        .order_by(IntegrationConnection.created_at.desc())
    )
    return list(result)


async def test_connection(
    session: AsyncSession,
    context: RequestContext,
    connection_id: str,
) -> IntegrationConnection:
    await require_capability(session, context, "connectors", operation="connector.test")
    connection = await get_connection(session, context, connection_id)
    if connection.status == "revoked":
        raise InvalidTransitionError("A revoked connection cannot be tested or reconnected")
    connector = get_connector(connection.provider_key)
    await connector.test(connection)
    connection.status = "connected"
    connection.last_tested_at = utc_now()
    connection.last_error_code = None
    await record_audit(
        session,
        context,
        "integration.connection.tested",
        "integration_connection",
        connection.id,
    )
    await session.commit()
    await session.refresh(connection)
    return connection
