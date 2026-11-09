from typing import cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.deps import RequestContext
from ..audit import record_audit, record_outbox_event
from ..domain import (
    ConflictError,
    InvalidRequestError,
    PreconditionRequiredError,
    VersionConflictError,
)
from ..models import TenantFeatureFlag, utc_now
from ..schemas import FeatureFlagRead
from .core import _read, _validate_flag

__all__ = [
    "set_flag",
]


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
