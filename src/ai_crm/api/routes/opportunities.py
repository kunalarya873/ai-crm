from typing import Annotated

from fastapi import Header, Query, Response, status

from ...domain import NotFoundError
from ...schemas import OpportunityCreate, OpportunityRead, OpportunityUpdate
from ...services import create_opportunity, get_opportunity, list_opportunities, update_opportunity
from .base import (
    OpportunityCreateContext,
    OpportunityReadContext,
    OpportunityUpdateContext,
    SessionDependency,
    router,
)
from .helpers import parse_if_match, set_etag, trim_page

__all__ = [
    "create_opportunity_endpoint", "get_opportunity_endpoint", "list_opportunities_endpoint",
    "update_opportunity_endpoint",
]


@router.post(
    "/opportunities",
    response_model=OpportunityRead,
    status_code=status.HTTP_201_CREATED,
    tags=["opportunities"],
)
async def create_opportunity_endpoint(
    payload: OpportunityCreate,
    response: Response,
    session: SessionDependency,
    context: OpportunityCreateContext,
) -> OpportunityRead:
    opportunity = await create_opportunity(session, context, payload)
    set_etag(response, opportunity.version)
    return OpportunityRead.model_validate(opportunity)


@router.get("/opportunities", response_model=list[OpportunityRead], tags=["opportunities"])
async def list_opportunities_endpoint(
    session: SessionDependency,
    context: OpportunityReadContext,
    response: Response,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    cursor: str | None = None,
    stage: str | None = None,
    owner_id: str | None = None,
    company_id: str | None = None,
    opportunity_status: str | None = Query(default=None, alias="status"),
) -> list[OpportunityRead]:
    opportunities = await list_opportunities(
        session,
        context,
        limit + 1,
        offset,
        stage=stage,
        owner_id=owner_id,
        company_id=company_id,
        opportunity_status=opportunity_status,
        cursor=cursor,
    )
    opportunities = trim_page(response, opportunities, limit)
    return [OpportunityRead.model_validate(opportunity) for opportunity in opportunities]


@router.get(
    "/opportunities/{opportunity_id}",
    response_model=OpportunityRead,
    tags=["opportunities"],
)
async def get_opportunity_endpoint(
    opportunity_id: str,
    response: Response,
    session: SessionDependency,
    context: OpportunityReadContext,
) -> OpportunityRead:
    opportunity = await get_opportunity(session, context, opportunity_id)
    if opportunity is None:
        raise NotFoundError("Opportunity not found")
    set_etag(response, opportunity.version)
    return OpportunityRead.model_validate(opportunity)


@router.patch(
    "/opportunities/{opportunity_id}",
    response_model=OpportunityRead,
    tags=["opportunities"],
)
async def update_opportunity_endpoint(
    opportunity_id: str,
    payload: OpportunityUpdate,
    response: Response,
    session: SessionDependency,
    context: OpportunityUpdateContext,
    if_match: Annotated[str | None, Header()] = None,
) -> OpportunityRead:
    opportunity = await update_opportunity(
        session,
        context,
        opportunity_id,
        payload,
        parse_if_match(if_match),
    )
    set_etag(response, opportunity.version)
    return OpportunityRead.model_validate(opportunity)
