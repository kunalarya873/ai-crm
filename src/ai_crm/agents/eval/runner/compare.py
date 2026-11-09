from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....api.deps import RequestContext
from ....domain import NotFoundError
from ....models import AgentEvalRun
from ....pagination import page_statement
from ..scenarios import STRATEGIES, Scenario
from .base import ASSUMPTIONS, get_scenario
from .execute import _stored

__all__ = [
    "aggregate", "build_comparison", "latest_comparison", "list_results",
]


async def list_results(
    session: AsyncSession,
    context: RequestContext,
    *,
    limit: int,
    offset: int,
    cursor: str | None,
    scenario_key: str | None = None,
) -> list[AgentEvalRun]:
    statement = select(AgentEvalRun).where(AgentEvalRun.tenant_id == context.tenant_id)
    if scenario_key:
        statement = statement.where(AgentEvalRun.scenario_key == scenario_key)
    return list(
        await session.scalars(page_statement(statement, AgentEvalRun, limit, offset, cursor))
    )


async def latest_comparison(
    session: AsyncSession, context: RequestContext, scenario_key: str, replay_key: str | None
) -> tuple[Scenario, dict[str, AgentEvalRun]]:
    scenario = get_scenario(scenario_key)
    if replay_key is None:
        latest = await session.scalar(
            select(AgentEvalRun)
            .where(
                AgentEvalRun.tenant_id == context.tenant_id,
                AgentEvalRun.scenario_key == scenario_key,
            )
            .order_by(AgentEvalRun.created_at.desc(), AgentEvalRun.id.desc())
            .limit(1)
        )
        if latest is None:
            raise NotFoundError("No evaluation results for this scenario")
        replay_key = latest.replay_key
    results = await _stored(session, context, scenario_key, replay_key)
    if not results:
        raise NotFoundError("No evaluation results for this replay_key")
    return scenario, results


def build_comparison(scenario: Scenario, results: dict[str, AgentEvalRun]) -> dict[str, Any]:
    strategies: dict[str, dict[str, Any]] = {
        name: {"task_success": row.task_success, **row.metrics} for name, row in results.items()
    }
    strategies["human_baseline"] = {
        "minutes": scenario.human.minutes,
        "human_interventions": scenario.human.interventions,
        "assumption": scenario.human.assumption,
    }
    deltas: dict[str, float | None] = {}
    single, multi = results.get("single_agent"), results.get("multi_agent")
    if single and multi:
        for name in (
            "steps",
            "failed_tool_calls",
            "duplicate_work",
            "human_interventions",
            "tokens",
            "cost_micros",
        ):
            deltas[name] = multi.metrics[name] - single.metrics[name]
    return {
        "scenario_key": scenario.key,
        "description": scenario.description,
        "strategies": strategies,
        "deltas_multi_minus_single": deltas,
        "assumptions": ASSUMPTIONS,
    }


def aggregate(report: list[tuple[Scenario, dict[str, AgentEvalRun]]]) -> dict[str, Any]:
    totals: dict[str, Any] = {}
    for strategy in STRATEGIES:
        rows = [results[strategy] for _, results in report if strategy in results]
        totals[strategy] = {
            "scenarios": len(rows),
            "successes": sum(1 for row in rows if row.task_success),
            "steps": sum(row.metrics["steps"] for row in rows),
            "tokens": sum(row.metrics["tokens"] for row in rows),
            "human_interventions": sum(row.metrics["human_interventions"] for row in rows),
        }
    return totals
