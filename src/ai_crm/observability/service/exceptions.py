from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import RequestContext
from ...models import (
    OperationalAlert,
    WorkItem,
)

__all__ = [
    "_ensure_exception",
]


async def _ensure_exception(
    session: AsyncSession,
    context: RequestContext,
    *,
    rule_key: str,
    alert_type: str,
    severity: str,
    title: str,
    description: str,
    related_type: str,
    related_id: str,
    evidence: list[dict[str, object]],
    now: datetime,
) -> tuple[int, int, int, int, str | None]:
    dedup_key = f"{rule_key}:{related_type}:{related_id}"
    alert = await session.scalar(
        select(OperationalAlert).where(
            OperationalAlert.tenant_id == context.tenant_id,
            OperationalAlert.dedup_key == dedup_key,
        )
    )
    if alert is not None and alert.status in {"open", "acknowledged"}:
        return 0, 0, 0, 1, alert.id
    reopened = 1 if alert is not None and alert.status == "resolved" else 0
    work_item_id = alert.work_item_id if alert is not None else None
    work_created = 0
    if work_item_id is None:
        work_item = WorkItem(
            tenant_id=context.tenant_id,
            item_type="escalation",
            title=f"Review exception: {title}",
            description=description,
            status="open",
            priority=80,
            owner_id=context.actor_id,
            source=f"proactive:{rule_key}",
            created_by=context.actor_id,
        )
        session.add(work_item)
        await session.flush()
        work_item_id = work_item.id
        work_created = 1
    if alert is None:
        alert = OperationalAlert(
            tenant_id=context.tenant_id,
            alert_type=alert_type,
            rule_key=rule_key,
            dedup_key=dedup_key,
            severity=severity,
            status="open",
            title=title,
            description=description,
            related_type=related_type,
            related_id=related_id,
            evidence=evidence,
            work_item_id=work_item_id,
        )
        session.add(alert)
        await session.flush()
    else:
        alert.status = "open"
        alert.evidence = evidence
        alert.resolved_by = None
        alert.resolved_at = None
        alert.resolution_note = None
        alert.updated_at = now
    return 1 if reopened == 0 else 0, reopened, work_created, 0, alert.id
