from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ....api.deps import RequestContext
from ....audit import record_audit, record_outbox_event
from ....domain import InvalidRequestError
from ....flags import require_capability
from ....models import AgentEvalRun
from ..scenarios import SCENARIOS, STRATEGIES, Scenario
from .base import _ensure_agents, get_scenario
from .execute import _execute, _stored

__all__ = [
    "run_evaluation",
]


async def run_evaluation(
    session: AsyncSession,
    context: RequestContext,
    scenario_key: str | None,
    replay_key: str,
) -> list[tuple[Scenario, dict[str, AgentEvalRun]]]:
    if not replay_key.strip():
        raise InvalidRequestError("replay_key is required")
    await require_capability(session, context, "agents", operation="agent.evaluation")
    scenarios = [get_scenario(scenario_key)] if scenario_key else list(SCENARIOS.values())
    agents = await _ensure_agents(session, context)
    report: list[tuple[Scenario, dict[str, AgentEvalRun]]] = []
    for scenario in scenarios:
        results = await _stored(session, context, scenario.key, replay_key)
        for strategy in STRATEGIES:
            if strategy in results:
                continue
            metrics, success, run_ids = await _execute(
                session, context, scenario, strategy, replay_key, agents
            )
            row = AgentEvalRun(
                tenant_id=context.tenant_id,
                scenario_key=scenario.key,
                strategy=strategy,
                replay_key=replay_key,
                task_success=success,
                metrics=metrics,
                run_ids=run_ids,
                created_by=context.actor_id,
            )
            session.add(row)
            try:
                await session.flush()
            except IntegrityError:
                await session.rollback()
                results = await _stored(session, context, scenario.key, replay_key)
                break
            details = {"scenario": scenario.key, "strategy": strategy, "success": success}
            await record_audit(
                session, context, "agent.evaluation.recorded", "agent_eval_run", row.id,
                details=details,
            )
            await record_outbox_event(
                session, context, "agent.evaluation.recorded", "agent_eval_run", row.id, details
            )
            await session.commit()
            results[strategy] = row
        report.append((scenario, results))
    return report
