from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import RequestContext
from ...config import settings
from ...models import Opportunity, WorkItem

__all__ = ["inactive_opportunity_rules", "overdue_work_item_rules"]


async def overdue_work_item_rules(
    session: AsyncSession, context: RequestContext, now: Any
) -> list[dict[str, Any]]:
    overdue_items = list(
        await session.scalars(
            select(WorkItem).where(
                WorkItem.tenant_id == context.tenant_id,
                WorkItem.due_at.is_not(None),
                WorkItem.due_at < now,
                WorkItem.status.not_in({"completed", "cancelled"}),
            )
        )
    )
    rules = []
    for item in overdue_items:
        due_at = item.due_at
        if due_at is None:
            continue
        rules.append(
            dict(
                rule_key="overdue_work_item",
                alert_type="business",
                severity="warning",
                title=f"Overdue work item: {item.title}",
                description="A work item is past due and still open.",
                related_type="work_item",
                related_id=item.id,
                evidence=[{"field": "due_at", "value": due_at.isoformat()}],
            )
        )
    return rules


async def inactive_opportunity_rules(
    session: AsyncSession, context: RequestContext, now: Any
) -> list[dict[str, Any]]:
    inactive_before = now - timedelta(days=settings.proactive_inactive_opportunity_days)
    inactive_opportunities = list(
        await session.scalars(
            select(Opportunity).where(
                Opportunity.tenant_id == context.tenant_id,
                Opportunity.status == "open",
                Opportunity.archived_at.is_(None),
                Opportunity.updated_at < inactive_before,
            )
        )
    )
    rules = []
    for opportunity in inactive_opportunities:
        opportunity_updated_at = opportunity.updated_at
        rules.append(
            dict(
                rule_key="inactive_opportunity",
                alert_type="business",
                severity="warning",
                title=f"Inactive opportunity: {opportunity.name}",
                description=(
                    "An open opportunity has not changed within the configured activity "
                    "window."
                ),
                related_type="opportunity",
                related_id=opportunity.id,
                evidence=[{"field": "updated_at", "value": opportunity_updated_at.isoformat()}],
            )
        )
    return rules
