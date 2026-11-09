from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.deps import RequestContext
from ..domain import InvalidRequestError
from ..models import Membership, User
from ..permissions import ROLE_PERMISSIONS
from ..schemas import MemberRead

__all__ = [
    "_active_admin_ids", "_read", "_validate_role", "list_members",
]


def _read(membership: Membership, user: User) -> MemberRead:
    return MemberRead(
        id=membership.id,
        user_id=membership.user_id,
        email=user.email,
        display_name=user.display_name,
        role=membership.role,
        is_active=membership.is_active,
        version=membership.version,
        created_at=membership.created_at,
    )


def _validate_role(role: str) -> None:
    if role not in ROLE_PERMISSIONS:
        raise InvalidRequestError(f"Unsupported role: {role}")


async def _active_admin_ids(session: AsyncSession, tenant_id: str) -> list[str]:
    # FOR UPDATE serialises concurrent role changes on databases that support row locks
    # (not SQLite), so two admins cannot demote each other at the same time.
    ids = await session.scalars(
        select(Membership.id)
        .join(User, User.id == Membership.user_id)
        .where(
            Membership.tenant_id == tenant_id,
            Membership.role == "admin",
            Membership.is_active.is_(True),
            User.is_active.is_(True),
        )
        .with_for_update()
    )
    return list(ids)


async def list_members(
    session: AsyncSession, context: RequestContext, limit: int, offset: int
) -> list[MemberRead]:
    rows = await session.execute(
        select(Membership, User)
        .join(User, User.id == Membership.user_id)
        .where(Membership.tenant_id == context.tenant_id)
        .order_by(Membership.created_at, Membership.id)
        .offset(offset)
        .limit(limit)
    )
    return [_read(membership, user) for membership, user in rows.all()]
