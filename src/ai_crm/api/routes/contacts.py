from typing import Annotated

from fastapi import Header, Query, Response, status

from ...domain import NotFoundError
from ...schemas import ContactCreate, ContactRead, ContactUpdate
from ...services import create_contact, get_contact, list_contacts, update_contact
from .base import (
    ContactCreateContext,
    ContactReadContext,
    ContactUpdateContext,
    SessionDependency,
    router,
)
from .helpers import parse_if_match, set_etag, trim_page

__all__ = [
    "create_contact_endpoint", "get_contact_endpoint", "list_contacts_endpoint",
    "update_contact_endpoint",
]


@router.post(
    "/contacts",
    response_model=ContactRead,
    status_code=status.HTTP_201_CREATED,
    tags=["contacts"],
)
async def create_contact_endpoint(
    payload: ContactCreate,
    response: Response,
    session: SessionDependency,
    context: ContactCreateContext,
) -> ContactRead:
    contact = await create_contact(session, context, payload)
    set_etag(response, contact.version)
    return ContactRead.model_validate(contact)


@router.get("/contacts", response_model=list[ContactRead], tags=["contacts"])
async def list_contacts_endpoint(
    session: SessionDependency,
    context: ContactReadContext,
    response: Response,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    cursor: str | None = None,
    company_id: str | None = None,
    owner_id: str | None = None,
    contact_status: str | None = Query(default=None, alias="status"),
    query: str | None = Query(default=None, alias="q"),
    archived: bool = False,
) -> list[ContactRead]:
    contacts = await list_contacts(
        session,
        context,
        limit + 1,
        offset,
        company_id=company_id,
        owner_id=owner_id,
        contact_status=contact_status,
        query=query,
        archived=archived,
        cursor=cursor,
    )
    contacts = trim_page(response, contacts, limit)
    return [ContactRead.model_validate(contact) for contact in contacts]


@router.get("/contacts/{contact_id}", response_model=ContactRead, tags=["contacts"])
async def get_contact_endpoint(
    contact_id: str,
    response: Response,
    session: SessionDependency,
    context: ContactReadContext,
) -> ContactRead:
    contact = await get_contact(session, context, contact_id)
    if contact is None:
        raise NotFoundError("Contact not found")
    set_etag(response, contact.version)
    return ContactRead.model_validate(contact)


@router.patch("/contacts/{contact_id}", response_model=ContactRead, tags=["contacts"])
async def update_contact_endpoint(
    contact_id: str,
    payload: ContactUpdate,
    response: Response,
    session: SessionDependency,
    context: ContactUpdateContext,
    if_match: Annotated[str | None, Header()] = None,
) -> ContactRead:
    contact = await update_contact(
        session,
        context,
        contact_id,
        payload,
        parse_if_match(if_match),
    )
    set_etag(response, contact.version)
    return ContactRead.model_validate(contact)
