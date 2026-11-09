from collections.abc import Sequence
from typing import Any

from fastapi import HTTPException, Response

from ...pagination import encode_cursor

__all__ = [
    "parse_if_match", "set_etag", "trim_page",
]


def parse_if_match(value: str | None, *, minimum: int = 1) -> int | None:
    if value is None:
        return None
    normalized = value.strip()
    if normalized.startswith("W/"):
        raise HTTPException(status_code=400, detail="If-Match must use a strong version value")
    normalized = normalized.strip('"')
    try:
        version = int(normalized)
    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail="If-Match must contain an integer version",
        ) from error
    if version < minimum:
        raise HTTPException(
            status_code=400,
            detail="If-Match must contain a positive integer version"
            if minimum > 0
            else "If-Match must contain a non-negative integer version",
        )
    return version


def set_etag(response: Response, version: int) -> None:
    response.headers["ETag"] = f'"{version}"'


def trim_page(response: Response, fetched: Sequence[Any], limit: int) -> Sequence[Any]:
    """Services fetch limit + 1 rows; the extra row proves another page exists."""
    items = fetched[:limit]
    if len(fetched) > limit:
        response.headers["X-Next-Cursor"] = encode_cursor(items[-1])
    return items
