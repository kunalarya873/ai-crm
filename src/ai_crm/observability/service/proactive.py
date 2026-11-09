from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import RequestContext
from ...audit import record_audit
from ...models import utc_now
from ...schemas import ProactiveCheckResponse
from .exceptions import _ensure_exception
from .guards import _require_manage
from .rules_business import inactive_opportunity_rules, overdue_work_item_rules
from .rules_system import failed_action_rules, failed_job_rules, reauth_connection_rules

__all__ = ["run_proactive_checks"]

RULE_FINDERS = (
    overdue_work_item_rules,
    inactive_opportunity_rules,
    reauth_connection_rules,
    failed_job_rules,
    failed_action_rules,
)


async def run_proactive_checks(
    session: AsyncSession,
    context: RequestContext,
) -> ProactiveCheckResponse:
    _require_manage(context)
    now = utc_now()
    created = 0
    reopened = 0
    work_created = 0
    suppressed = 0
    alert_ids: list[str] = []

    for find_rules in RULE_FINDERS:
        for rule in await find_rules(session, context, now):
            result = await _ensure_exception(session, context, now=now, **rule)
            created += result[0]
            reopened += result[1]
            work_created += result[2]
            suppressed += result[3]
            if result[4]:
                alert_ids.append(result[4])

    await record_audit(
        session,
        context,
        "observability.proactive_checks.completed",
        "proactive_check",
        context.correlation_id,
        details={
            "alerts_created": created,
            "alerts_reopened": reopened,
            "work_items_created": work_created,
            "suppressed_duplicates": suppressed,
        },
    )
    await session.commit()
    return ProactiveCheckResponse(
        checked_at=now,
        alerts_created=created,
        alerts_reopened=reopened,
        work_items_created=work_created,
        suppressed_duplicates=suppressed,
        alert_ids=alert_ids,
    )
