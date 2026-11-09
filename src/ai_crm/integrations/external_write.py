from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.deps import RequestContext
from ..audit import record_audit
from ..domain import ConflictError, InvalidRequestError
from ..flags import require_capability
from ..models import ExternalWrite
from ..schemas import ExternalWriteCreate
from .connections import get_connection
from .contract import ConnectorProviderError
from .fixture import connection_is_writable, get_connector, request_hash

__all__ = [
    "create_external_write",
]


async def create_external_write(
    session: AsyncSession,
    context: RequestContext,
    connection_id: str,
    payload: ExternalWriteCreate,
    idempotency_key: str,
) -> ExternalWrite:
    await require_capability(session, context, "connectors", operation="connector.write")
    if not idempotency_key.strip():
        raise InvalidRequestError("Idempotency-Key header is required")
    connection = await get_connection(session, context, connection_id)
    connection_is_writable(connection)
    digest = request_hash(payload.payload)
    existing = await session.scalar(
        select(ExternalWrite).where(
            ExternalWrite.connection_id == connection.id,
            ExternalWrite.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_hash != digest:
            raise ConflictError("Idempotency-Key was reused with a different payload")
        return existing

    write = ExternalWrite(
        connection_id=connection.id,
        idempotency_key=idempotency_key,
        operation=payload.operation,
        request_hash=digest,
        status="pending",
        attempts=1,
    )
    session.add(write)
    await session.flush()
    connector = get_connector(connection.provider_key)
    try:
        result = await connector.write(
            connection,
            payload.operation,
            payload.payload,
            idempotency_key,
        )
        write.status = "succeeded"
        write.provider_request_id = result.provider_request_id
        write.response_metadata = result.response_metadata
    except ConnectorProviderError as error:
        write.status = "failed"
        write.last_error = error.code
    await record_audit(
        session,
        context,
        "integration.external_write.completed",
        "external_write",
        write.id,
        details={"status": write.status, "operation": write.operation},
    )
    await session.commit()
    await session.refresh(write)
    return write
