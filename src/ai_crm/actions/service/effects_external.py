from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import RequestContext
from ...domain import NotFoundError
from ...integrations import ConnectorProviderError, connection_is_writable, get_connector
from ...models import ActionExecution, ExternalWrite, IntegrationConnection, utc_now
from ..registry import ExternalActivityAction
from .common import _hash_payload

__all__ = [
    "_create_external_activity",
]


async def _create_external_activity(
    session: AsyncSession,
    context: RequestContext,
    payload: BaseModel,
    execution: ActionExecution,
) -> dict[str, object]:
    action = ExternalActivityAction.model_validate(payload.model_dump())
    connection = await session.scalar(
        select(IntegrationConnection).where(
            IntegrationConnection.id == action.connection_id,
            IntegrationConnection.tenant_id == context.tenant_id,
        )
    )
    if connection is None:
        raise NotFoundError("Integration connection not found")
    connection_is_writable(connection)
    write = await session.scalar(
        select(ExternalWrite).where(
            ExternalWrite.connection_id == connection.id,
            ExternalWrite.idempotency_key == execution.idempotency_key,
        )
    )
    if write is None:
        write = ExternalWrite(
            connection_id=connection.id,
            idempotency_key=execution.idempotency_key,
            operation="activity.create",
            request_hash=_hash_payload("activity.create", action.model_dump(mode="json")),
            status="pending",
            attempts=execution.attempts,
        )
        session.add(write)
        await session.flush()
    elif write.status == "succeeded":
        return {
            "external_write_id": write.id,
            "provider_request_id": write.provider_request_id,
            "response_metadata": write.response_metadata,
            "replayed": True,
        }
    connector = get_connector(connection.provider_key)
    try:
        result = await connector.write(
            connection,
            "activity.create",
            {"subject": action.subject, "body": action.body},
            execution.idempotency_key,
        )
    except ConnectorProviderError as error:
        write.status = "failed"
        write.last_error = error.code
        raise
    write.status = "succeeded"
    write.provider_request_id = result.provider_request_id
    write.response_metadata = result.response_metadata
    write.updated_at = utc_now()
    execution.provider_request_id = result.provider_request_id
    return {
        "external_write_id": write.id,
        "provider_request_id": result.provider_request_id,
        "response_metadata": result.response_metadata,
    }
