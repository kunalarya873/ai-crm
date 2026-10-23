from collections.abc import AsyncIterator

import httpx
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ai_crm.db import get_session
from ai_crm.main import app
from ai_crm.models import Base, Membership, Organization, User


@pytest_asyncio.fixture
async def client(tmp_path) -> AsyncIterator[httpx.AsyncClient]:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        session.add_all(
            [
                Organization(id="tenant-a", name="Tenant A"),
                Organization(id="tenant-b", name="Tenant B"),
                User(id="user-a", email="user-a@example.com", display_name="User A"),
                User(id="user-b", email="user-b@example.com", display_name="User B"),
                Membership(tenant_id="tenant-a", user_id="user-a", role="member"),
                Membership(tenant_id="tenant-b", user_id="user-a", role="member"),
                Membership(tenant_id="tenant-a", user_id="user-b", role="viewer"),
            ]
        )
        await session.commit()

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client

    app.dependency_overrides.clear()
    await engine.dispose()
