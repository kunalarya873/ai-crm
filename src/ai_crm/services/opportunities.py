from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.deps import RequestContext
from ..domain import (
    ALLOWED_OPPORTUNITY_STAGE_TRANSITIONS,
    InvalidRequestError,
)
from ..models import Opportunity
from ..pagination import page_statement
from ..schemas import (
    OpportunityCreate,
)
from .events import _record_create_events
from .lookups import _validate_relationships

__all__ = [
    "create_opportunity", "get_opportunity", "list_opportunities",
]


async def create_opportunity(
    session: AsyncSession,
    context: RequestContext,
    payload: OpportunityCreate,
) -> Opportunity:
    if not payload.company_id and not payload.contact_id:
        raise InvalidRequestError("An opportunity must be linked to a company or contact")
    if payload.stage not in ALLOWED_OPPORTUNITY_STAGE_TRANSITIONS:
        raise InvalidRequestError("Invalid opportunity stage")
    if payload.status not in {"open", "won", "lost"}:
        raise InvalidRequestError("Invalid opportunity status")
    await _validate_relationships(
        session,
        context,
        company_id=payload.company_id,
        contact_id=payload.contact_id,
    )
    opportunity = Opportunity(tenant_id=context.tenant_id, **payload.model_dump())
    session.add(opportunity)
    await session.flush()
    await _record_create_events(
        session,
        context,
        action="opportunity.created",
        entity_type="opportunity",
        entity_id=opportunity.id,
        version=opportunity.version,
    )
    await session.commit()
    await session.refresh(opportunity)
    return opportunity


async def list_opportunities(
    session: AsyncSession,
    context: RequestContext,
    limit: int,
    offset: int,
    *,
    stage: str | None = None,
    owner_id: str | None = None,
    company_id: str | None = None,
    opportunity_status: str | None = None,
    cursor: str | None = None,
) -> Sequence[Opportunity]:
    statement = select(Opportunity).where(
        Opportunity.tenant_id == context.tenant_id,
        Opportunity.archived_at.is_(None),
    )
    if stage:
        statement = statement.where(Opportunity.stage == stage)
    if owner_id:
        statement = statement.where(Opportunity.owner_id == owner_id)
    if company_id:
        statement = statement.where(Opportunity.company_id == company_id)
    if opportunity_status:
        statement = statement.where(Opportunity.status == opportunity_status)
    result = await session.scalars(page_statement(statement, Opportunity, limit, offset, cursor))
    return result.all()


async def get_opportunity(
    session: AsyncSession,
    context: RequestContext,
    opportunity_id: str,
) -> Opportunity | None:
    return await session.scalar(
        select(Opportunity).where(
            Opportunity.id == opportunity_id,
            Opportunity.tenant_id == context.tenant_id,
        )
    )
