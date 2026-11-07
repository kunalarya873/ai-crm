from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..actions.registry import ACTION_REGISTRY
from ..api.deps import RequestContext
from ..audit import record_audit, record_outbox_event
from ..config import settings
from ..domain import (
    ConflictError,
    InvalidRequestError,
    NotFoundError,
    PreconditionRequiredError,
    VersionConflictError,
)
from ..models import Agent, Membership, utc_now
from ..pagination import page_statement
from ..schemas import AgentCreate, AgentUpdate
from .domain import RISK_ORDER, validate_agent_transition


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


async def register_agent(
    session: AsyncSession, context: RequestContext, payload: AgentCreate
) -> Agent:
    capabilities = _unique(list(payload.allowed_capabilities))
    actions = _unique(payload.allowed_actions)
    validate_agent_config(
        capabilities=capabilities,
        actions=actions,
        risk_ceiling=payload.risk_ceiling,
        max_depth=payload.max_depth,
        max_fanout=payload.max_fanout,
        token_budget=payload.token_budget,
        step_budget=payload.step_budget,
        side_effect_budget=payload.side_effect_budget,
    )
    owner_id = payload.owner_id or context.actor_id
    membership = await session.scalar(
        select(Membership.id).where(
            Membership.tenant_id == context.tenant_id,
            Membership.user_id == owner_id,
            Membership.is_active.is_(True),
        )
    )
    if membership is None:
        raise InvalidRequestError("Agent owner must be an active member of this tenant")
    duplicate = await session.scalar(
        select(Agent.id).where(Agent.tenant_id == context.tenant_id, Agent.key == payload.key)
    )
    if duplicate is not None:
        raise ConflictError("An agent with this key already exists")
    agent = Agent(
        tenant_id=context.tenant_id,
        key=payload.key,
        name=payload.name,
        purpose=payload.purpose,
        agent_version=payload.agent_version,
        owner_id=owner_id,
        allowed_capabilities=capabilities,
        allowed_actions=actions,
        allow_sensitive=payload.allow_sensitive,
        risk_ceiling=payload.risk_ceiling,
        max_depth=payload.max_depth,
        max_fanout=payload.max_fanout,
        token_budget=payload.token_budget,
        step_budget=payload.step_budget,
        side_effect_budget=payload.side_effect_budget,
    )
    session.add(agent)
    try:
        await session.flush()
    except IntegrityError as error:
        await session.rollback()
        raise ConflictError("An agent with this key already exists") from error
    details = {
        "key": agent.key,
        "agent_version": agent.agent_version,
        "capabilities": capabilities,
        "allowed_actions": actions,
    }
    await record_audit(session, context, "agent.registered", "agent", agent.id, details=details)
    await record_outbox_event(session, context, "agent.registered", "agent", agent.id, details)
    await session.commit()
    await session.refresh(agent)
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


async def update_agent(
    session: AsyncSession,
    context: RequestContext,
    agent_id: str,
    payload: AgentUpdate,
    expected_version: int | None,
) -> Agent:
    if expected_version is None:
        raise PreconditionRequiredError("If-Match header is required")
    agent = await get_agent(session, context, agent_id)
    if agent.version != expected_version:
        raise VersionConflictError("record_version_conflict")
    changes = payload.model_dump(exclude_unset=True)
    if "allowed_capabilities" in changes:
        changes["allowed_capabilities"] = _unique(changes["allowed_capabilities"])
    if "allowed_actions" in changes:
        changes["allowed_actions"] = _unique(changes["allowed_actions"])
    for field in ("name", "purpose", "agent_version", "allow_sensitive", "risk_ceiling", "status"):
        if field in changes and changes[field] is None:
            raise InvalidRequestError(f"{field} cannot be null")
    if "status" in changes:
        validate_agent_transition(agent.status, changes["status"])
    def pick(name: str, current: Any) -> Any:
        return current if changes.get(name) is None else changes[name]

    merged = {
        "capabilities": pick("allowed_capabilities", agent.allowed_capabilities),
        "actions": pick("allowed_actions", agent.allowed_actions),
        "risk_ceiling": pick("risk_ceiling", agent.risk_ceiling),
        "max_depth": pick("max_depth", agent.max_depth),
        "max_fanout": pick("max_fanout", agent.max_fanout),
        "token_budget": pick("token_budget", agent.token_budget),
        "step_budget": pick("step_budget", agent.step_budget),
        "side_effect_budget": pick("side_effect_budget", agent.side_effect_budget),
    }
    config_fields = set(changes) - {"name", "purpose", "agent_version", "status"}
    if config_fields:
        validate_agent_config(**merged)
    values = {key: value for key, value in changes.items() if value is not None}
    updated = cast(
        CursorResult,
        await session.execute(
            update(Agent)
            .where(
                Agent.id == agent.id,
                Agent.tenant_id == context.tenant_id,
                Agent.version == expected_version,
            )
            .values(**values, version=expected_version + 1, updated_at=utc_now())
        ),
    )
    if updated.rowcount != 1:
        await session.rollback()
        raise VersionConflictError("record_version_conflict")
    details = {"key": agent.key, "changes": sorted(values)}
    await record_audit(session, context, "agent.updated", "agent", agent.id, details=details)
    await record_outbox_event(session, context, "agent.updated", "agent", agent.id, details)
    await session.commit()
    await session.refresh(agent)
    return agent
