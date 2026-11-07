from typing import cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .api.deps import RequestContext
from .audit import record_audit, record_outbox_event
from .domain import (
    ConflictError,
    InvalidRequestError,
    NotFoundError,
    PreconditionRequiredError,
    VersionConflictError,
)
from .models import Membership, User
from .permissions import ROLE_PERMISSIONS
from .schemas import MemberCreate, MemberRead, MemberUpdate


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
