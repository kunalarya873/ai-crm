import json
from datetime import UTC, datetime

from ..domain import InvalidRequestError
from .fixture import MAX_WEBHOOK_EVENT_ID_LENGTH

__all__ = ["_parse_timestamp", "parse_payload"]


def parse_payload(raw_body: bytes) -> tuple[dict, str, str]:
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as error:
        raise InvalidRequestError("Webhook payload is not valid JSON") from error
    if not isinstance(payload, dict):
        raise InvalidRequestError("Webhook payload must be an object")
    event_id = payload.get("id")
    event_type = payload.get("type")
    if not isinstance(event_id, str) or not event_id.strip():
        raise InvalidRequestError("Webhook event id is required")
    if len(event_id) > MAX_WEBHOOK_EVENT_ID_LENGTH:
        raise InvalidRequestError(
            f"Webhook event id is longer than {MAX_WEBHOOK_EVENT_ID_LENGTH} characters"
        )
    if not isinstance(event_type, str) or not event_type.strip():
        raise InvalidRequestError("Webhook event type is required")
    return payload, event_id, event_type


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise InvalidRequestError("Webhook timestamp is invalid") from error
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
