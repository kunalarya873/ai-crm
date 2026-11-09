from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import RequestContext
from ...domain import InvalidRequestError, NotFoundError
from ...models import Contact, Opportunity, WorkItem

__all__ = [
    "_same_instant", "_validate_references", "get_work_item",
]


def _same_instant(left, right) -> bool:
    if left.tzinfo is None:
        left = left.replace(tzinfo=right.tzinfo)
    return left == right


async def get_work_item(
    session: AsyncSession,
    context: RequestContext,
    work_item_id: str,
) -> WorkItem:
    item = await session.scalar(
        select(WorkItem).where(
            WorkItem.id == work_item_id,
            WorkItem.tenant_id == context.tenant_id,
        )
    )
    if item is None:
        raise NotFoundError("Work item not found")
    return item


async def _validate_references(
    session: AsyncSession,
    context: RequestContext,
    *,
    contact_id: str | None = None,
    opportunity_id: str | None = None,
    dependency_ids: list[str] | None = None,
    current_id: str | None = None,
) -> None:
    if contact_id is not None:
        contact = await session.scalar(
            select(Contact).where(
                Contact.id == contact_id,
                Contact.tenant_id == context.tenant_id,
            )
        )
        if contact is None:
            raise NotFoundError("Contact not found")
    if opportunity_id is not None:
        opportunity = await session.scalar(
            select(Opportunity).where(
                Opportunity.id == opportunity_id,
                Opportunity.tenant_id == context.tenant_id,
            )
        )
        if opportunity is None:
            raise NotFoundError("Opportunity not found")
    dependency_ids = dependency_ids or []
    if current_id and current_id in dependency_ids:
        raise InvalidRequestError("A work item cannot depend on itself")
    if len(dependency_ids) != len(set(dependency_ids)):
        raise InvalidRequestError("Work item dependencies must be unique")
    if dependency_ids:
        result = await session.scalars(
            select(WorkItem).where(
                WorkItem.tenant_id == context.tenant_id,
                WorkItem.id.in_(dependency_ids),
            )
        )
        found = {item.id for item in result}
        if found != set(dependency_ids):
            raise NotFoundError("A work item dependency was not found")
