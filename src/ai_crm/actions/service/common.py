import hashlib
import json
from datetime import UTC, datetime

from ...api.deps import RequestContext
from ...domain import (
    ConflictError,
    InvalidRequestError,
    InvalidTransitionError,
    NotFoundError,
    VersionConflictError,
)
from ...models import (
    ActionProposal,
    utc_now,
)
from ...permissions import Permission

__all__ = [
    "EXECUTION_STATUSES", "PROPOSAL_STATUSES", "_aware", "_check_version", "_ensure_not_expired",
    "_error_code", "_hash_payload", "_json_safe", "_require_permission",
]


PROPOSAL_STATUSES = frozenset(
    {
        "proposed",
        "edited",
        "approved",
        "rejected",
        "expired",
        "revoked",
        "executing",
        "succeeded",
        "failed",
        "recoverable",
    }
)


EXECUTION_STATUSES = frozenset(
    {"executing", "succeeded", "failed", "recoverable", "uncertain", "cancelled"}
)


def _hash_payload(action_type: str, payload: dict[str, object]) -> str:
    encoded = json.dumps(
        {"action_type": action_type, "payload": payload},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(encoded.encode()).hexdigest()


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _json_safe(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def _require_permission(context: RequestContext, permission: Permission) -> None:
    if permission not in context.permissions:
        raise InvalidRequestError(f"Action requires permission: {permission.value}")


def _check_version(proposal: ActionProposal, expected_version: int | None) -> None:
    if expected_version is None:
        raise InvalidRequestError("If-Match header is required")
    if proposal.version != expected_version:
        raise VersionConflictError("record_version_conflict")


def _ensure_not_expired(proposal: ActionProposal) -> None:
    expires_at = _aware(proposal.expires_at)
    if expires_at is not None and expires_at <= utc_now():
        raise ConflictError("Action proposal has expired")


def _error_code(error: Exception) -> str:
    if isinstance(error, VersionConflictError):
        return "record_version_conflict"
    if isinstance(error, InvalidRequestError):
        return "invalid_request"
    if isinstance(error, NotFoundError):
        return "not_found"
    if isinstance(error, InvalidTransitionError):
        return "invalid_transition"
    return "action_failed"
