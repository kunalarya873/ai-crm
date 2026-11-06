import hashlib
from datetime import datetime

SENSITIVE_KEYS = frozenset(
    {
        "authorization",
        "body",
        "content",
        "email",
        "secret",
        "secret_ref",
        "token",
        "password",
        "prompt",
        "output",
        "text",
    }
)


def _hash_value(value: object) -> str:
    return hashlib.sha256(str(value).encode()).hexdigest()[:16]


def redact_telemetry(value: object, *, key: str | None = None) -> object:
    normalized_key = key.casefold() if key else ""
    if normalized_key in SENSITIVE_KEYS:
        return {"redacted": True, "hash": _hash_value(value)}
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {
            str(item_key): redact_telemetry(item_value, key=str(item_key))
            for item_key, item_value in value.items()
        }
    if isinstance(value, list):
        return [redact_telemetry(item) for item in value]
    if isinstance(value, tuple):
        return [redact_telemetry(item) for item in value]
    return value
