from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....api.deps import RequestContext
from ....domain import ConflictError, NotFoundError
from ....models import Agent
from ....schemas import AgentCreate
from ...registry import register_agent
from ..scenarios import EVAL_AGENTS, SCENARIOS, Op, Scenario

__all__ = [
    "ASSUMPTIONS", "_ensure_agents", "_step_input", "get_scenario",
]


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
