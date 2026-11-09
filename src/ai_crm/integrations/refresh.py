from sqlalchemy.ext.asyncio import AsyncSession

from ..api.deps import RequestContext
from ..audit import record_audit, record_outbox_event
from ..domain import InvalidRequestError, InvalidTransitionError
from ..flags import require_capability
from ..models import IntegrationConnection
from .connections import get_connection
from .contract import TRANSIENT_PROVIDER_CODES, ConnectorProviderError
from .fixture import get_connector

__all__ = [
    "refresh_connection", "set_connection_status",
]


async def refresh_connection(
    session: AsyncSession,
    context: RequestContext,
    connection_id: str,
) -> IntegrationConnection:
    await require_capability(session, context, "connectors", operation="connector.refresh")
    connection = await get_connection(session, context, connection_id)
    if connection.status not in {"connected", "needs_reauth"}:
        raise InvalidTransitionError(
            "Only connected or needs_reauth connections can be refreshed "
            f"(status: {connection.status})"
        )
    connector = get_connector(connection.provider_key)
    try:
        expires_at = await connector.refresh(connection)
    except ConnectorProviderError as error:
        connection.last_error_code = error.code
        if error.code not in TRANSIENT_PROVIDER_CODES and connection.status == "connected":
            connection.status = "needs_reauth"
            await record_audit(
                session,
                context,
                "integration.connection.needs_reauth",
                "integration_connection",
                connection.id,
                outcome="failed",
                reason=error.code,
            )
            await record_outbox_event(
                session,
                context,
                "integration.connection.needs_reauth",
                "integration_connection",
                connection.id,
            )
        await record_audit(
            session,
            context,
            "integration.connection.refresh_failed",
            "integration_connection",
            connection.id,
            outcome="failed",
            reason=error.code,
        )
        await session.commit()
        raise
    connection.token_expires_at = expires_at
    connection.last_error_code = None
    connection.status = "connected"
    await record_audit(
        session,
        context,
        "integration.connection.refreshed",
        "integration_connection",
        connection.id,
    )
    await record_outbox_event(
        session,
        context,
        "integration.connection.refreshed",
        "integration_connection",
        connection.id,
    )
    await session.commit()
    await session.refresh(connection)
    return connection


async def set_connection_status(
    session: AsyncSession,
    context: RequestContext,
    connection_id: str,
    new_status: str,
) -> IntegrationConnection:
    connection = await get_connection(session, context, connection_id)
    if new_status not in {"disconnected", "revoked"}:
        raise InvalidRequestError("Unsupported connection status change")
    connection.status = new_status
    await record_audit(
        session,
        context,
        f"integration.connection.{new_status}",
        "integration_connection",
        connection.id,
    )
    await record_outbox_event(
        session,
        context,
        f"integration.connection.{new_status}",
        "integration_connection",
        connection.id,
    )
    await session.commit()
    await session.refresh(connection)
    return connection
