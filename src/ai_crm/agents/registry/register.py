from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import RequestContext
from ...audit import record_audit, record_outbox_event
from ...domain import ConflictError, InvalidRequestError
from ...models import Agent, Membership
from ...schemas import AgentCreate
from .read import _unique, validate_agent_config

__all__ = [
    "register_agent",
]


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
