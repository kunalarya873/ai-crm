import hashlib
import json
import logging
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from ...actions.registry import ACTION_REGISTRY
from ...api.deps import RequestContext
from ...audit import record_audit, record_outbox_event
from ...domain import (
    NotFoundError,
    PermissionDeniedError,
    VersionConflictError,
)
from ...models import Agent, AgentRun, utc_now
from ...permissions import Permission

__all__ = [
    "_NEVER_GRANTED", "_audit_run", "_authorize", "_aware", "_digest", "_get_agent",
    "_run_details", "_update_run", "agent_context", "get_run", "logger",
]


logger = logging.getLogger(__name__)


# Agents can never approve, execute or recover actions, whatever their owner may do.
_NEVER_GRANTED = frozenset(
    {Permission.ACTIONS_APPROVE, Permission.ACTIONS_EXECUTE, Permission.ACTIONS_RECOVER}
)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _digest(*parts: object) -> str:
    raw = json.dumps(parts, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def agent_context(agent: Agent, context: RequestContext) -> RequestContext:
    """The owner's permissions narrowed to what this agent's capabilities allow."""
    allowed: set[Permission] = set()
    if "read" in agent.allowed_capabilities:
        allowed |= {Permission.KNOWLEDGE_READ, Permission.KNOWLEDGE_CONTEXT}
        if agent.allow_sensitive:
            allowed.add(Permission.KNOWLEDGE_SENSITIVE)
    if "propose" in agent.allowed_capabilities:
        allowed.add(Permission.ACTIONS_PROPOSE)
        for action_type in agent.allowed_actions:
            definition = ACTION_REGISTRY.get(action_type)
            if definition is not None:
                allowed.add(definition.required_permission)
    allowed -= _NEVER_GRANTED
    return replace(context, permissions=context.permissions & frozenset(allowed))


async def get_run(session: AsyncSession, context: RequestContext, run_id: str) -> AgentRun:
    run = await session.scalar(
        select(AgentRun).where(AgentRun.id == run_id, AgentRun.tenant_id == context.tenant_id)
    )
    if run is None:
        raise NotFoundError("Agent run not found")
    return run


async def _get_agent(session: AsyncSession, tenant_id: str, agent_id: str) -> Agent | None:
    return await session.scalar(
        select(Agent).where(Agent.id == agent_id, Agent.tenant_id == tenant_id)
    )


def _authorize(context: RequestContext, run: AgentRun, *, allow_manage: bool) -> None:
    if context.actor_id == run.owner_id:
        return
    if allow_manage and Permission.AGENTS_MANAGE in context.permissions:
        return
    raise PermissionDeniedError("Only the run owner can act on this agent run")


async def _update_run(session: AsyncSession, run: AgentRun, **values: Any) -> None:
    """Compare-and-swap on the run version, so concurrent steps cannot both spend one budget."""
    updated = cast(
        CursorResult,
        await session.execute(
            update(AgentRun)
            .where(
                AgentRun.id == run.id,
                AgentRun.tenant_id == run.tenant_id,
                AgentRun.version == run.version,
            )
            .values(**values, version=run.version + 1, updated_at=utc_now())
        ),
    )
    if updated.rowcount != 1:
        await session.rollback()
        raise VersionConflictError("record_version_conflict")
    await session.refresh(run)


def _run_details(run: AgentRun, **extra: Any) -> dict[str, Any]:
    return {
        "run_id": run.id,
        "root_run_id": run.root_run_id,
        "agent_key": run.agent_key,
        "agent_version": run.agent_version,
        **extra,
    }


async def _audit_run(
    session: AsyncSession,
    context: RequestContext,
    run: AgentRun,
    action: str,
    **extra: Any,
) -> None:
    details = _run_details(run, **extra)
    await record_audit(session, context, action, "agent_run", run.id, details=details)
    await record_outbox_event(session, context, action, "agent_run", run.id, details)
