from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.deps import RequestContext
from ..audit import record_audit
from ..domain import ConflictError, InvalidRequestError, LegalHoldError, NotFoundError
from ..models import LegalHold, utc_now
from ..schemas import LegalHoldCreate, LegalHoldRelease
from .fields import ERASABLE

__all__ = [
    "active_hold",
    "create_hold",
    "list_holds",
    "release_hold",
]


async def active_hold(
    session: AsyncSession,
    tenant_id: str,
    resource_type: str | None = None,
    record_id: str | None = None,
) -> LegalHold | None:
    """A tenant-wide hold, or a hold on this record, that has not been released."""
    scope = LegalHold.scope == "tenant"
    if resource_type is not None and record_id is not None:
        scope = scope | (
            (LegalHold.resource_type == resource_type) & (LegalHold.record_id == record_id)
        )
    return await session.scalar(
        select(LegalHold)
        .where(LegalHold.tenant_id == tenant_id, LegalHold.released_at.is_(None), scope)
        .order_by(LegalHold.created_at)
        .limit(1)
    )


async def create_hold(
    session: AsyncSession, context: RequestContext, payload: LegalHoldCreate
) -> LegalHold:
    if payload.scope == "tenant":
        if payload.resource_type is not None or payload.record_id is not None:
            raise InvalidRequestError("A tenant-wide hold cannot name a record")
    else:
        spec = ERASABLE.get(payload.resource_type or "")
        if spec is None or not payload.record_id:
            raise InvalidRequestError("A record hold needs a supported resource_type and record_id")
        found = await session.scalar(
            select(spec.model.id).where(
                spec.model.id == payload.record_id, spec.model.tenant_id == context.tenant_id
            )
        )
        if found is None:
            raise NotFoundError("Record not found")
    duplicate = await session.scalar(
        select(LegalHold).where(
            LegalHold.tenant_id == context.tenant_id,
            LegalHold.released_at.is_(None),
            LegalHold.scope == payload.scope,
            LegalHold.resource_type.is_(payload.resource_type)
            if payload.resource_type is None
            else LegalHold.resource_type == payload.resource_type,
            LegalHold.record_id.is_(payload.record_id)
            if payload.record_id is None
            else LegalHold.record_id == payload.record_id,
        )
    )
    if duplicate is not None:
        return duplicate  # a retried request must not stack a second hold
    hold = LegalHold(
        tenant_id=context.tenant_id,
        scope=payload.scope,
        resource_type=payload.resource_type,
        record_id=payload.record_id,
        reason=payload.reason.strip(),
        created_by=context.actor_id,
    )
    session.add(hold)
    await session.flush()
    await record_audit(
        session,
        context,
        "legal_hold.created",
        "legal_hold",
        hold.id,
        details={
            "scope": hold.scope,
            "resource_type": hold.resource_type,
            "record_id": hold.record_id,
        },
    )
    await session.commit()
    await session.refresh(hold)
    return hold


async def list_holds(
    session: AsyncSession, context: RequestContext, *, active: bool | None = None
) -> list[LegalHold]:
    statement = select(LegalHold).where(LegalHold.tenant_id == context.tenant_id)
    if active is True:
        statement = statement.where(LegalHold.released_at.is_(None))
    elif active is False:
        statement = statement.where(LegalHold.released_at.is_not(None))
    rows = await session.scalars(statement.order_by(LegalHold.created_at.desc(), LegalHold.id))
    return list(rows)


async def release_hold(
    session: AsyncSession, context: RequestContext, hold_id: str, payload: LegalHoldRelease
) -> LegalHold:
    hold = await session.scalar(
        select(LegalHold).where(LegalHold.id == hold_id, LegalHold.tenant_id == context.tenant_id)
    )
    if hold is None:
        raise NotFoundError("Legal hold not found")
    if hold.released_at is not None:
        raise ConflictError("Legal hold was already released")
    hold.released_at = utc_now()
    hold.released_by = context.actor_id
    hold.release_reason = payload.reason.strip()
    await record_audit(session, context, "legal_hold.released", "legal_hold", hold.id)
    await session.commit()
    await session.refresh(hold)
    return hold


async def require_no_hold(
    session: AsyncSession,
    context: RequestContext,
    operation: str,
    resource_type: str | None = None,
    record_id: str | None = None,
) -> None:
    """Raise LegalHoldError (after auditing the refused attempt) when a hold applies."""
    hold = await active_hold(session, context.tenant_id, resource_type, record_id)
    if hold is None:
        return
    await record_audit(
        session,
        context,
        operation,
        resource_type or "tenant",
        record_id or context.tenant_id,
        outcome="denied",
        reason="legal_hold",
        details={"hold_id": hold.id},
    )
    await session.commit()
    raise LegalHoldError(f"A legal hold prevents {operation} until it is released")
