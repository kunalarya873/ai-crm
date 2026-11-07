import base64
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Select, and_, or_

from .domain import InvalidRequestError


def encode_cursor(item: Any) -> str:
    raw = json.dumps({"t": item.created_at.isoformat(), "i": item.id}, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode()))
        created_at = datetime.fromisoformat(data["t"])
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        return created_at, str(data["i"])
    except (ValueError, KeyError, TypeError) as error:
        raise InvalidRequestError("Invalid pagination cursor") from error


def page_statement(
    statement: Select[Any], model: Any, limit: int, offset: int, cursor: str | None
) -> Select[Any]:
    """Order newest-first with a stable id tiebreak; page by keyset cursor or legacy offset."""
    statement = statement.order_by(model.created_at.desc(), model.id.desc())
    if cursor is None:
        return statement.offset(offset).limit(limit)
    if offset:
        raise InvalidRequestError("Use either cursor or offset, not both")
    created_at, item_id = decode_cursor(cursor)
    return statement.where(
        or_(
            model.created_at < created_at,
            and_(model.created_at == created_at, model.id < item_id),
        )
    ).limit(limit)
