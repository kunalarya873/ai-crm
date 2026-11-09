from datetime import UTC, datetime, timedelta

from ...api.deps import RequestContext
from ...domain import InvalidRequestError
from ...models import (
    utc_now,
)
from ...permissions import Permission

__all__ = [
    "_as_utc", "_require_manage", "_require_read", "_window",
]


def _require_manage(context: RequestContext) -> None:
    if Permission.OBSERVABILITY_MANAGE not in context.permissions:
        raise InvalidRequestError("Observability management permission is required")


def _require_read(context: RequestContext) -> None:
    if Permission.OBSERVABILITY_READ not in context.permissions:
        raise InvalidRequestError("Observability read permission is required")


def _window(
    window_start: datetime | None,
    window_end: datetime | None,
) -> tuple[datetime, datetime]:
    end = window_end or utc_now()
    start = window_start or end - timedelta(hours=24)
    if start.tzinfo is None or end.tzinfo is None:
        raise InvalidRequestError("Metric windows must include a timezone")
    if start >= end:
        raise InvalidRequestError("Metric window start must be before window end")
    return start.astimezone(UTC), end.astimezone(UTC)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
