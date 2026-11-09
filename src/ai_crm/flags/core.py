from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.deps import RequestContext
from ..audit import record_audit
from ..config import CAPABILITY_FLAGS, settings
from ..domain import CapabilityDisabledError, NotFoundError
from ..models import TenantFeatureFlag
from ..permissions import Permission
from ..schemas import FeatureFlagRead

__all__ = [
    "_read", "_rows", "_validate_flag", "disabled_flags", "effective_flags", "is_enabled",
    "require_capability", "system_context",
]


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
