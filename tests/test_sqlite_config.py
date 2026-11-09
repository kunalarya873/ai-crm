import asyncio
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ai_crm.db import build_engine, configure_sqlite
from ai_crm.models import Base, Organization

pytestmark = pytest.mark.sqlite_only


async def pragma(engine, name: str) -> object:
    async with engine.connect() as connection:
        return (await connection.execute(text(f"PRAGMA {name}"))).scalar()


@pytest.mark.parametrize(("wal", "mode", "synchronous"), [(True, "wal", 1), (False, "delete", 2)])
async def test_pragmas_follow_the_wal_setting(
    tmp_path: Path, wal: bool, mode: str, synchronous: int
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'p.db'}")
    configure_sqlite(engine, wal=wal)
    try:
        assert await pragma(engine, "journal_mode") == mode
        assert await pragma(engine, "synchronous") == synchronous
        assert await pragma(engine, "busy_timeout") == 5000  # Python's sqlite3 default
    finally:
        await engine.dispose()


def test_non_sqlite_urls_are_left_alone() -> None:
    class Untouchable:
        url = make_url("postgresql+asyncpg://user:pw@localhost/none")

        @property
        def sync_engine(self) -> object:
            raise AssertionError("a non-SQLite engine must not be touched")

    configure_sqlite(Untouchable(), wal=True)  # type: ignore[arg-type]


async def test_concurrent_writers_in_wal_mode_lose_nothing(tmp_path: Path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'w.db'}")
    configure_sqlite(engine, wal=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async def write(number: int) -> None:
        async with factory() as session:
            session.add(Organization(id=f"org-{number}", name=f"Org {number}"))
            await session.commit()

    try:
        await asyncio.gather(*(write(number) for number in range(30)))
        async with engine.connect() as connection:
            count = (await connection.execute(text("SELECT COUNT(*) FROM organizations"))).scalar()
        assert count == 30
    finally:
        await engine.dispose()


async def test_turning_wal_off_reverts_a_file_left_in_wal(tmp_path: Path) -> None:
    url = f"sqlite+aiosqlite:///{tmp_path / 'r.db'}"
    first = build_engine(url, wal=True)
    try:
        assert await pragma(first, "journal_mode") == "wal"
    finally:
        await first.dispose()

    second = build_engine(url, wal=False)
    try:
        assert await pragma(second, "journal_mode") == "delete"
    finally:
        await second.dispose()


async def test_build_engine_applies_the_setting(tmp_path: Path) -> None:
    engine = build_engine(f"sqlite+aiosqlite:///{tmp_path / 'b.db'}", wal=True)
    try:
        assert await pragma(engine, "journal_mode") == "wal"
    finally:
        await engine.dispose()
