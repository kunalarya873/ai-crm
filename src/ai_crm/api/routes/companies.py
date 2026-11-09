from typing import Annotated

from fastapi import Header, Query, Response, status

from ...schemas import CompanyCreate, CompanyRead, CompanyUpdate
from ...services import create_company, get_company_for_tenant, list_companies, update_company
from .base import (
    CompanyCreateContext,
    CompanyReadContext,
    CompanyUpdateContext,
    SessionDependency,
    router,
)
from .helpers import parse_if_match, set_etag, trim_page

__all__ = [
    "create_company_endpoint", "get_company_endpoint", "list_companies_endpoint",
    "update_company_endpoint",
]


@router.post(
    "/companies",
    response_model=CompanyRead,
    status_code=status.HTTP_201_CREATED,
    tags=["companies"],
)
async def create_company_endpoint(
    payload: CompanyCreate,
    response: Response,
    session: SessionDependency,
    context: CompanyCreateContext,
) -> CompanyRead:
    company = await create_company(session, context, payload)
    set_etag(response, company.version)
    return CompanyRead.model_validate(company)


@router.get("/companies", response_model=list[CompanyRead], tags=["companies"])
async def list_companies_endpoint(
    session: SessionDependency,
    context: CompanyReadContext,
    response: Response,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    cursor: str | None = None,
) -> list[CompanyRead]:
    companies = await list_companies(session, context, limit + 1, offset, cursor=cursor)
    companies = trim_page(response, companies, limit)
    return [CompanyRead.model_validate(company) for company in companies]


@router.get("/companies/{company_id}", response_model=CompanyRead, tags=["companies"])
async def get_company_endpoint(
    company_id: str,
    response: Response,
    session: SessionDependency,
    context: CompanyReadContext,
) -> CompanyRead:
    company = await get_company_for_tenant(session, context, company_id)
    set_etag(response, company.version)
    return CompanyRead.model_validate(company)


@router.patch("/companies/{company_id}", response_model=CompanyRead, tags=["companies"])
async def update_company_endpoint(
    company_id: str,
    payload: CompanyUpdate,
    response: Response,
    session: SessionDependency,
    context: CompanyUpdateContext,
    if_match: Annotated[str | None, Header()] = None,
) -> CompanyRead:
    company = await update_company(
        session,
        context,
        company_id,
        payload,
        parse_if_match(if_match),
    )
    set_etag(response, company.version)
    return CompanyRead.model_validate(company)
