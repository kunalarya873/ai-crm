from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.deps import RequestContext
from ..audit import record_audit, record_outbox_event
from ..domain import ConflictError, NotFoundError
from ..models import Membership, User
from ..schemas import MemberCreate, MemberRead
from .read import _read, _validate_role

__all__ = [
    "add_member",
]


async def add_member(
    session: AsyncSession, context: RequestContext, payload: MemberCreate
) -> MemberRead:
    _validate_role(payload.role)
    user = await session.scalar(
        select(User).where(User.email == payload.email, User.is_active.is_(True))
    )
    if user is None:
        raise NotFoundError("No active user exists with that email")
    existing = await session.scalar(
        select(Membership).where(
            Membership.tenant_id == context.tenant_id, Membership.user_id == user.id
        )
    )
    if existing is not None:
        raise ConflictError("User already has a membership in this tenant")
    membership = Membership(tenant_id=context.tenant_id, user_id=user.id, role=payload.role)
    session.add(membership)
    try:
        await session.flush()
    except IntegrityError as error:
        await session.rollback()
        raise ConflictError("User already has a membership in this tenant") from error
    details = {"user_id": user.id, "role": membership.role}
    await record_audit(
        session, context, "member.added", "membership", membership.id, details=details
    )
    await record_outbox_event(
        session, context, "member.added", "membership", membership.id, details
    )
    await session.commit()
    await session.refresh(membership)
    return _read(membership, user)
