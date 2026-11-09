from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.deps import RequestContext
from ..domain import ConflictError, InvalidRequestError, VersionConflictError, normalize_name
from ..lifecycle import ensure_not_erased
from ..models import Company
from ..schemas import CompanyUpdate
from .common import require_version, utc_now
from .events import _record_update_events
from .lookups import get_company_for_tenant

__all__ = [
    "update_company",
]


async def update_company(
    session: AsyncSession,
    context: RequestContext,
    company_id: str,
    payload: CompanyUpdate,
    expected_version: int | None,
) -> Company:
    expected = require_version(expected_version)
    company = await get_company_for_tenant(session, context, company_id)
    await ensure_not_erased(session, context, "companies", company_id)
    if company.version != expected:
        raise VersionConflictError("record_version_conflict")
    changes = payload.model_dump(exclude_unset=True)
    archived = changes.pop("archived", None)
    if not changes and archived is None:
        raise InvalidRequestError("At least one field is required")
    if "name" in changes:
        normalized_name = normalize_name(changes["name"])
        duplicate = await session.scalar(
            select(Company).where(
                Company.tenant_id == context.tenant_id,
                Company.normalized_name == normalized_name,
                Company.id != company_id,
            )
        )
        if duplicate is not None:
            raise ConflictError("A company with this name already exists in this tenant")
        changes["normalized_name"] = normalized_name
    if archived is not None:
        changes["archived_at"] = utc_now() if archived else None
    old_state = {key: getattr(company, key) for key in changes if hasattr(company, key)}
    changes.update(version=expected + 1, updated_at=utc_now())
    result = cast(
        CursorResult[Any],
        await session.execute(
            update(Company)
            .where(
                Company.id == company_id,
                Company.tenant_id == context.tenant_id,
                Company.version == expected,
            )
            .values(**changes)
        ),
    )
    if result.rowcount != 1:
        await session.rollback()
        raise VersionConflictError("record_version_conflict")
    await _record_update_events(
        session,
        context,
        action="company.updated",
        entity_type="company",
        entity_id=company_id,
        old_state=old_state,
        new_state=changes,
        version=expected + 1,
    )
    await session.commit()
    await session.refresh(company)
    return company
