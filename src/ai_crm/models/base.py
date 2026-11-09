from datetime import UTC, datetime

from sqlalchemy.orm import DeclarativeBase

__all__ = [
    "Base", "utc_now",
]


def utc_now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass
