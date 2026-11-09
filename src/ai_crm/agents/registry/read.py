from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...actions.registry import ACTION_REGISTRY
from ...api.deps import RequestContext
from ...config import settings
from ...domain import InvalidRequestError, NotFoundError
from ...models import Agent
from ...pagination import page_statement
from ..domain import RISK_ORDER

__all__ = [
    "_unique", "get_agent", "list_agents", "validate_agent_config",
]


def validate_agent_config(
    *,
    capabilities: list[str],
    actions: list[str],
    risk_ceiling: str,
    max_depth: int,
    max_fanout: int,
    token_budget: int,
    step_budget: int,
    side_effect_budget: int,
) -> None:
    if ("propose" in capabilities) != bool(actions):
        raise InvalidRequestError(
            "allowed_actions must be non-empty exactly when the propose capability is granted"
        )
    for action_type in actions:
        definition = ACTION_REGISTRY.get(action_type)
        if definition is None:
            raise InvalidRequestError(f"Action is not in the central registry: {action_type}")
        if RISK_ORDER[definition.risk_level] > RISK_ORDER[risk_ceiling]:
            raise InvalidRequestError(
                f"Action {action_type} is {definition.risk_level} risk, above the agent ceiling"
            )
    if "delegate" in capabilities and (max_depth < 1 or max_fanout < 1):
        raise InvalidRequestError("delegate capability needs max_depth and max_fanout of 1+")
    limits = (
        ("max_depth", max_depth, settings.agent_max_depth_cap),
        ("max_fanout", max_fanout, settings.agent_max_fanout_cap),
        ("token_budget", token_budget, settings.agent_token_budget_cap),
        ("step_budget", step_budget, settings.agent_step_budget_cap),
        ("side_effect_budget", side_effect_budget, settings.agent_side_effect_budget_cap),
    )
    for name, value, cap in limits:
        if value > cap:
            raise InvalidRequestError(f"{name} exceeds the platform cap of {cap}")


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


async def get_agent(session: AsyncSession, context: RequestContext, agent_id: str) -> Agent:
    agent = await session.scalar(
        select(Agent).where(Agent.id == agent_id, Agent.tenant_id == context.tenant_id)
    )
    if agent is None:
        raise NotFoundError("Agent not found")
    return agent


async def list_agents(
    session: AsyncSession,
    context: RequestContext,
    *,
    limit: int,
    offset: int,
    cursor: str | None,
    status: str | None = None,
) -> list[Agent]:
    statement = select(Agent).where(Agent.tenant_id == context.tenant_id)
    if status:
        statement = statement.where(Agent.status == status)
    return list(await session.scalars(page_statement(statement, Agent, limit, offset, cursor)))
