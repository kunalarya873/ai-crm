from datetime import timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....api.deps import RequestContext
from ....config import settings
from ....domain import ConflictError
from ....models import Agent, AgentEvalRun, AgentMessage, AgentRun, AgentStep, utc_now
from ....schemas import AgentRunCreate, AgentStepCreate
from ...runs import start_run, submit_step
from ..metrics import task_success, tree_metrics
from ..scenarios import Scenario
from .base import _step_input

__all__ = [
    "_execute", "_stored",
]


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
