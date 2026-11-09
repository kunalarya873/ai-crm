from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.deps import RequestContext
from ..audit import record_audit, record_outbox_event
from ..domain import (
    ConflictError,
    normalize_name,
)
from ..models import Company
from ..pagination import page_statement
from ..schemas import (
    CompanyCreate,
)

__all__ = [
    "create_company", "list_companies",
]


async def create_company(
    session: AsyncSession,
    context: RequestContext,
    payload: CompanyCreate,
) -> Company:
    normalized_name = normalize_name(payload.name)
    existing = await session.scalar(
        select(Company).where(
            Company.tenant_id == context.tenant_id,
            Company.normalized_name == normalized_name,
        )
    )
    if existing is not None:
        raise ConflictError("A company with this name already exists in this tenant")
    company = Company(
        tenant_id=context.tenant_id,
        normalized_name=normalized_name,
        **payload.model_dump(),
    )
    session.add(company)
    await session.flush()
    await record_audit(
        session=session,
        context=context,
        action="company.created",
        entity_type="company",
        entity_id=company.id,
        details={"version": company.version},
    )
    await record_outbox_event(
        session=session,
        context=context,
        event_type="company.created",
        aggregate_type="company",
        aggregate_id=company.id,
        payload={"version": company.version},
    )
    await session.commit()
    await session.refresh(company)
    return company


async def list_companies(
    session: AsyncSession,
    context: RequestContext,
    limit: int,
    offset: int,
    *,
    cursor: str | None = None,
) -> Sequence[Company]:
    statement = select(Company).where(
        Company.tenant_id == context.tenant_id, Company.archived_at.is_(None)
    )
    result = await session.scalars(page_statement(statement, Company, limit, offset, cursor))
    return result.all()
