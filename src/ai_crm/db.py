from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import event, select, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .config import settings
from .models import Base, Membership, Organization, User


def configure_sqlite(engine: AsyncEngine, *, wal: bool) -> None:
    """SQLite-only connection tuning; other databases are left untouched.

    The journal mode is stored in the database file, so each connection reads it and switches only
    when it differs from the setting (this also reverts a file left in WAL by an earlier run).
    WAL lets readers proceed during a write and, with synchronous=NORMAL, avoids an fsync of the
    journal and the database on every commit; it is not safe on network filesystems. The busy
    timeout stays at Python's sqlite3 default of 5 seconds."""
    if not engine.url.get_backend_name().startswith("sqlite"):
        return
    wanted = "wal" if wal else "delete"

    def apply(dbapi_connection: Any, connection_record: Any) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode")
            current = str(cursor.fetchone()[0]).lower()
            if current != wanted:
                cursor.execute(f"PRAGMA journal_mode={wanted}")
            if wal:
                cursor.execute("PRAGMA synchronous=NORMAL")
        finally:
            cursor.close()

    event.listen(engine.sync_engine, "connect", apply)


def build_engine(url: str, *, wal: bool, echo: bool = False) -> AsyncEngine:
    engine = create_async_engine(url, echo=echo)
    configure_sqlite(engine, wal=wal)
    return engine


engine = build_engine(settings.database_url, wal=settings.sqlite_wal, echo=settings.debug)
SessionFactory = async_sessionmaker(engine, expire_on_commit=False)


async def create_tables() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def close_database() -> None:
    await engine.dispose()


async def check_database() -> None:
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))


async def seed_local_identity() -> None:
    async with SessionFactory() as session:
        await _seed_identity(session)


async def _seed_identity(session: AsyncSession) -> None:
    if await session.get(Organization, "demo-tenant") is None:
        session.add(Organization(id="demo-tenant", name="Demo Tenant"))
    for user_id, email, display_name, role in (
        ("demo-user", "demo@example.com", "Demo User", "admin"),
        ("demo-manager", "demo-manager@example.com", "Demo Manager", "manager"),
    ):
        if await session.get(User, user_id) is None:
            session.add(User(id=user_id, email=email, display_name=display_name))
        membership = await session.scalar(
            select(Membership).where(
                Membership.tenant_id == "demo-tenant",
                Membership.user_id == user_id,
            )
        )
        if membership is None:
            session.add(Membership(tenant_id="demo-tenant", user_id=user_id, role=role))
    await session.commit()


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionFactory() as session:
        yield session
