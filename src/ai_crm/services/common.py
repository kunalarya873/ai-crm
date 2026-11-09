from datetime import UTC, datetime

from ..domain import PreconditionRequiredError

__all__ = [
    "json_safe", "require_version", "utc_now",
]


def utc_now() -> datetime:
    return datetime.now(UTC)


def json_safe(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    return value


def require_version(expected_version: int | None) -> int:
    if expected_version is None:
        raise PreconditionRequiredError("If-Match header is required")
    if expected_version < 1:
        raise ValueError("If-Match must contain a positive integer version")
    return expected_version
