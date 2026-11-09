from typing import Annotated

from fastapi import Header, Request, status

from ...integrations import (
    ingest_webhook,
)
from ...schemas import (
    WebhookAccepted,
)
from .base import SessionDependency, router

__all__ = [
    "receive_webhook_endpoint",
]


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
    event, duplicate = await ingest_webhook(
        session,
        provider_key,
        external_account_id or "",
        signature or "",
        raw_body,
        getattr(request.state, "trace_id", None),
    )
    return WebhookAccepted(
        id=event.id,
        provider_event_id=event.provider_event_id,
        status="duplicate" if duplicate else event.status,
    )
