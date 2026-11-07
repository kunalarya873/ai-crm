from datetime import timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import RequestContext
from ...audit import record_audit, record_outbox_event
from ...config import settings
from ...domain import ConflictError, InvalidRequestError, NotFoundError
from ...flags import require_capability
from ...models import Agent, AgentEvalRun, AgentMessage, AgentRun, AgentStep, utc_now
from ...pagination import page_statement
from ...schemas import AgentCreate, AgentRunCreate, AgentStepCreate
from ..registry import register_agent
from ..runs import start_run, submit_step
from .metrics import task_success, tree_metrics
from .scenarios import EVAL_AGENTS, SCENARIOS, STRATEGIES, Op, Scenario

ASSUMPTIONS = [
    "Scenarios are scripted step sequences replayed through the real coordination services; "
    "no model is involved, so results measure the coordination machinery, not model quality.",
    "Human-baseline minutes and interventions are declared assumptions, not measurements.",
    "Token counts are scripted per step; cost is tokens times AGENT_COST_PER_1K_TOKENS_MICROS.",
]


def get_scenario(key: str) -> Scenario:
    scenario = SCENARIOS.get(key)
    if scenario is None:
        raise NotFoundError(f"Unknown evaluation scenario: {key}")
    return scenario


async def _ensure_agents(session: AsyncSession, context: RequestContext) -> dict[str, Agent]:
    agents: dict[str, Agent] = {}
    for alias, spec in EVAL_AGENTS.items():
        agent = await session.scalar(
            select(Agent).where(Agent.tenant_id == context.tenant_id, Agent.key == spec["key"])
        )
        if agent is None:
            is_lead = alias == "lead"
            agent = await register_agent(
                session,
                context,
                AgentCreate(
                    key=spec["key"],
                    name=f"Evaluation {alias}",
                    purpose="Built-in coordination evaluation agent",
                    owner_id=context.actor_id,
                    allowed_capabilities=spec["allowed_capabilities"],
                    allowed_actions=["task.create"],
                    risk_ceiling="low",
                    max_depth=spec["max_depth"],
                    max_fanout=spec["max_fanout"],
                    token_budget=10000,
                    step_budget=20,
                    side_effect_budget=3 if is_lead else 2,
                ),
            )
        if agent.status != "active":
            raise ConflictError(f"Evaluation agent {agent.key} is {agent.status}")
        agents[alias] = agent
    return agents


def _step_input(op: Op, agents: dict[str, Agent], child_deadline: str) -> dict[str, Any]:
    if op.step_type != "delegate":
        return op.input
    return {
        "agent_key": agents[op.input["worker"]].key,
        "reason": "Scripted evaluation handoff",
        "objective": op.input["objective"],
        "expected_result": "Scripted result",
        "deadline_at": child_deadline,
        "token_budget": op.input.get("token_budget", 1000),
        "step_budget": op.input.get("step_budget", 10),
        "side_effect_budget": op.input.get("side_effect_budget", 1),
    }


async def _execute(
    session: AsyncSession,
    context: RequestContext,
    scenario: Scenario,
    strategy: str,
    replay_key: str,
    agents: dict[str, Agent],
) -> tuple[dict[str, Any], bool, list[str]]:
    now = utc_now()
    root = await start_run(
        session,
        context,
        AgentRunCreate(
            agent_id=agents["lead"].id,
            objective=scenario.objective,
            deadline_at=now + timedelta(minutes=30),
            side_effect_budget=scenario.root_side_effects,
        ),
        f"eval:{scenario.key}:{strategy}:{replay_key}:{uuid4().hex}",
    )
    child_deadline = (now + timedelta(minutes=29)).isoformat()
    aliases = {"root": root.id}
    for op in scenario.script(strategy):
        try:
            result = await submit_step(
                session,
                context,
                aliases[op.run],
                AgentStepCreate(
                    step_key=op.key,
                    step_type=op.step_type,  # type: ignore[arg-type]
                    input=_step_input(op, agents, child_deadline),
                    tokens=op.tokens,
                ),
            )
        except ConflictError:
            if not op.tolerate:
                raise
            continue
        if op.child and result.step.child_run_id:
            aliases[op.child] = result.step.child_run_id
    runs = list(
        await session.scalars(
            select(AgentRun).where(
                AgentRun.tenant_id == context.tenant_id, AgentRun.root_run_id == root.id
            )
        )
    )
    run_ids = [run.id for run in runs]
    steps = list(
        await session.scalars(
            select(AgentStep).where(
                AgentStep.tenant_id == context.tenant_id, AgentStep.run_id.in_(run_ids)
            )
        )
    )
    messages = list(
        await session.scalars(
            select(AgentMessage).where(
                AgentMessage.tenant_id == context.tenant_id, AgentMessage.root_run_id == root.id
            )
        )
    )
    metrics = tree_metrics(
        root.id,
        runs,
        steps,
        messages,
        cost_per_1k_micros=settings.agent_cost_per_1k_tokens_micros,
    )
    return metrics, task_success(metrics, scenario.expect), run_ids


async def _stored(
    session: AsyncSession, context: RequestContext, scenario_key: str, replay_key: str
) -> dict[str, AgentEvalRun]:
    rows = await session.scalars(
        select(AgentEvalRun).where(
            AgentEvalRun.tenant_id == context.tenant_id,
            AgentEvalRun.scenario_key == scenario_key,
            AgentEvalRun.replay_key == replay_key,
        )
    )
    return {row.strategy: row for row in rows}


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
