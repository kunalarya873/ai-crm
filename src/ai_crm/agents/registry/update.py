from typing import Any, cast

from sqlalchemy import update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import RequestContext
from ...audit import record_audit, record_outbox_event
from ...domain import (
    InvalidRequestError,
    PreconditionRequiredError,
    VersionConflictError,
)
from ...models import Agent, utc_now
from ...schemas import AgentUpdate
from ..domain import validate_agent_transition
from .read import _unique, get_agent, validate_agent_config

__all__ = [
    "update_agent",
]


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
