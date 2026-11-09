from typing import cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.deps import RequestContext
from ..audit import record_audit, record_outbox_event
from ..domain import (
    ConflictError,
    NotFoundError,
    PreconditionRequiredError,
    VersionConflictError,
)
from ..models import Membership, User
from ..schemas import MemberRead, MemberUpdate
from .read import _active_admin_ids, _read, _validate_role

__all__ = [
    "update_member",
]


async def update_member(
    session: AsyncSession,
    context: RequestContext,
    membership_id: str,
    payload: MemberUpdate,
    expected_version: int | None,
) -> MemberRead:
    if expected_version is None:
        raise PreconditionRequiredError("If-Match header is required")
    membership = await session.scalar(
        select(Membership).where(
            Membership.id == membership_id, Membership.tenant_id == context.tenant_id
        ).with_for_update()
    )
    if membership is None:
        raise NotFoundError("Membership not found")
    user = await session.get_one(User, membership.user_id)
    if membership.version != expected_version:
        raise VersionConflictError("record_version_conflict")
    new_role = payload.role if payload.role is not None else membership.role
    new_active = payload.is_active if payload.is_active is not None else membership.is_active
    _validate_role(new_role)
    if new_role == membership.role and new_active == membership.is_active:
        return _read(membership, user)

    stays_admin = new_role == "admin" and new_active
    if not stays_admin:
        admin_ids = await _active_admin_ids(session, context.tenant_id)
        if membership.id in admin_ids and len(admin_ids) <= 1:
            raise ConflictError("A tenant must keep at least one active admin")

    events: list[str] = []
    if new_role != membership.role:
        events.append("member.role_changed")
    if new_active != membership.is_active:
        events.append("member.reactivated" if new_active else "member.deactivated")
    details = {
        "user_id": membership.user_id,
        "old": {"role": membership.role, "is_active": membership.is_active},
        "new": {"role": new_role, "is_active": new_active},
    }
    updated = cast(
        CursorResult,
        await session.execute(
            update(Membership)
            .where(
                Membership.id == membership.id,
                Membership.tenant_id == context.tenant_id,
                Membership.version == expected_version,
            )
            .values(role=new_role, is_active=new_active, version=expected_version + 1)
        ),
    )
    if updated.rowcount != 1:
        await session.rollback()
        raise VersionConflictError("record_version_conflict")
    for event in events:
        await record_audit(
            session, context, event, "membership", membership.id, details=details
        )
        await record_outbox_event(
            session, context, event, "membership", membership.id, details
        )
    await session.commit()
    await session.refresh(membership)
    return _read(membership, user)
