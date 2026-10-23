from collections.abc import AsyncIterator

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .config import settings
from .models import Base, Membership, Organization, User

engine = create_async_engine(settings.database_url, echo=settings.debug)
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
        organization = await session.get(Organization, "demo-tenant")
        if organization is None:
            session.add(Organization(id="demo-tenant", name="Demo Tenant"))

        user = await session.get(User, "demo-user")
        if user is None:
            session.add(
                User(
                    id="demo-user",
                    email="demo@example.com",
                    display_name="Demo User",
                )
            )

        membership = await session.scalar(
            select(Membership).where(
                Membership.tenant_id == "demo-tenant",
                Membership.user_id == "demo-user",
            )
        )
        if membership is None:
            session.add(
                Membership(
                    tenant_id="demo-tenant",
                    user_id="demo-user",
                    role="admin",
                )
            )
        await session.commit()


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionFactory() as session:
        yield session
