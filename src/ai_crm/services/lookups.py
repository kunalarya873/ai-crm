from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.deps import RequestContext
from ..domain import NotFoundError
from ..models import Company, Contact, Opportunity

__all__ = [
    "_validate_relationships", "get_company_for_tenant", "get_contact_for_tenant",
    "get_opportunity_for_tenant",
]


async def get_company_for_tenant(
    session: AsyncSession,
    context: RequestContext,
    company_id: str,
) -> Company:
    company = await session.scalar(
        select(Company).where(Company.id == company_id, Company.tenant_id == context.tenant_id)
    )
    if company is None:
        raise NotFoundError("Company not found")
    return company


async def get_contact_for_tenant(
    session: AsyncSession,
    context: RequestContext,
    contact_id: str,
) -> Contact:
    contact = await session.scalar(
        select(Contact).where(Contact.id == contact_id, Contact.tenant_id == context.tenant_id)
    )
    if contact is None:
        raise NotFoundError("Contact not found")
    return contact


async def get_opportunity_for_tenant(
    session: AsyncSession,
    context: RequestContext,
    opportunity_id: str,
) -> Opportunity:
    opportunity = await session.scalar(
        select(Opportunity).where(
            Opportunity.id == opportunity_id,
            Opportunity.tenant_id == context.tenant_id,
        )
    )
    if opportunity is None:
        raise NotFoundError("Opportunity not found")
    return opportunity


async def _validate_relationships(
    session: AsyncSession,
    context: RequestContext,
    *,
    company_id: str | None = None,
    contact_id: str | None = None,
    opportunity_id: str | None = None,
) -> None:
    if company_id is not None:
        await get_company_for_tenant(session, context, company_id)
    if contact_id is not None:
        await get_contact_for_tenant(session, context, contact_id)
    if opportunity_id is not None:
        await get_opportunity_for_tenant(session, context, opportunity_id)
