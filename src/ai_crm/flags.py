from typing import cast
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .api.deps import RequestContext
from .audit import record_audit, record_outbox_event
from .config import CAPABILITY_FLAGS, settings
from .domain import (
    CapabilityDisabledError,
    ConflictError,
    InvalidRequestError,
    NotFoundError,
    PreconditionRequiredError,
    VersionConflictError,
)
from .models import TenantFeatureFlag, utc_now
from .permissions import Permission
from .schemas import FeatureFlagRead


def _validate_flag(flag: str) -> None:
    if flag not in CAPABILITY_FLAGS:
        raise NotFoundError(f"Unknown capability flag: {flag}")


async def _rows(session: AsyncSession, tenant_id: str) -> dict[str, TenantFeatureFlag]:
    rows = await session.scalars(
        select(TenantFeatureFlag).where(TenantFeatureFlag.tenant_id == tenant_id)
    )
    return {row.flag_key: row for row in rows}


def _read(flag: str, row: TenantFeatureFlag | None) -> FeatureFlagRead:
    if flag in settings.disabled_capability_set:
        return FeatureFlagRead(
            flag=flag,
            enabled=False,
            source="platform",
            reason="Disabled platform-wide by the operator",
            version=row.version if row else 0,
        )
    if row is None:
        return FeatureFlagRead(flag=flag, enabled=True, source="default", reason=None, version=0)
    return FeatureFlagRead(
        flag=flag,
        enabled=row.enabled,
        source="tenant",
        reason=row.reason,
        version=row.version,
        updated_by=row.updated_by,
        updated_at=row.updated_at,
    )


async def effective_flags(session: AsyncSession, tenant_id: str) -> list[FeatureFlagRead]:
    rows = await _rows(session, tenant_id)
    return [_read(flag, rows.get(flag)) for flag in CAPABILITY_FLAGS]


async def is_enabled(session: AsyncSession, tenant_id: str, flag: str) -> bool:
    if flag in settings.disabled_capability_set:
        return False
    row = await session.scalar(
        select(TenantFeatureFlag).where(
            TenantFeatureFlag.tenant_id == tenant_id, TenantFeatureFlag.flag_key == flag
        )
    )
    return row is None or row.enabled


async def disabled_flags(session: AsyncSession, tenant_id: str) -> frozenset[str]:
    flags = await effective_flags(session, tenant_id)
    return frozenset(item.flag for item in flags if not item.enabled)


async def require_capability(
    session: AsyncSession, context: RequestContext, flag: str, *, operation: str
) -> None:
    """Refuse new work for a switched-off capability, leaving a committed denial audit row."""
    if await is_enabled(session, context.tenant_id, flag):
        return
    await record_audit(
        session,
        context,
        "capability.blocked",
        "capability",
        flag,
        outcome="denied",
        reason="capability_disabled",
        details={"operation": operation},
    )
    await session.commit()
    raise CapabilityDisabledError(f"The {flag} capability is currently disabled")


def system_context(tenant_id: str, actor_id: str) -> RequestContext:
    return RequestContext(
        tenant_id=tenant_id,
        actor_id=actor_id,
        role="system",
        correlation_id=str(uuid4()),
        permissions=frozenset({Permission.ADMIN_FLAGS_READ}),
    )


async def set_flag(
    session: AsyncSession,
    context: RequestContext,
    flag: str,
    *,
    enabled: bool,
    reason: str | None,
    expected_version: int | None,
) -> FeatureFlagRead:
    _validate_flag(flag)
    if expected_version is None:
        raise PreconditionRequiredError("If-Match header is required")
    cleaned = reason.strip() if reason else None
    if not enabled and not cleaned:
        raise InvalidRequestError("A reason is required when disabling a capability")
    row = await session.scalar(
        select(TenantFeatureFlag).where(
            TenantFeatureFlag.tenant_id == context.tenant_id, TenantFeatureFlag.flag_key == flag
        )
    )
    current_version = row.version if row else 0
    if current_version != expected_version:
        raise VersionConflictError("record_version_conflict")
    if row is None:
        row = TenantFeatureFlag(
            tenant_id=context.tenant_id,
            flag_key=flag,
            enabled=enabled,
            reason=cleaned,
            updated_by=context.actor_id,
        )
        session.add(row)
        try:
            await session.flush()
        except IntegrityError as error:
            await session.rollback()
            raise ConflictError("The capability flag was changed concurrently") from error
        previous = True
    else:
        previous = row.enabled
        updated = cast(
            CursorResult,
            await session.execute(
                update(TenantFeatureFlag)
                .where(
                    TenantFeatureFlag.id == row.id,
                    TenantFeatureFlag.tenant_id == context.tenant_id,
                    TenantFeatureFlag.version == expected_version,
                )
                .values(
                    enabled=enabled,
                    reason=cleaned,
                    updated_by=context.actor_id,
                    version=expected_version + 1,
                    updated_at=utc_now(),
                )
            ),
        )
        if updated.rowcount != 1:
            await session.rollback()
            raise VersionConflictError("record_version_conflict")
    event = "capability.enabled" if enabled else "capability.disabled"
    details = {"flag": flag, "previous_enabled": previous, "enabled": enabled, "reason": cleaned}
    await record_audit(session, context, event, "capability", flag, details=details)
    await record_outbox_event(session, context, event, "capability", flag, details)
    await session.commit()
    await session.refresh(row)
    return _read(flag, row)
