from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...actions.registry import ACTION_REGISTRY
from ...actions.service import create_proposal, describe_proposal
from ...api.deps import RequestContext
from ...models import ActionProposal, Agent, AgentRun, AgentStep
from ...schemas import ActionProposalCreate, AgentStepCreate
from ..domain import OPEN_PROPOSAL_STATUSES, RISK_ORDER
from .base import agent_context
from .escalate import _Escalation
from .outcome import _budget_exhausted, _denial, _Outcome, _parse

__all__ = [
    "_do_propose", "_proposal_keys", "_resource_keys", "_root_open_proposals",
]


def _resource_keys(resources: list[dict[str, Any]]) -> set[tuple[str, str]]:
    return {
        (str(item.get("resource_type")), str(item.get("resource_id")))
        for item in resources
        if item.get("resource_type") and item.get("resource_id")
    }


def _proposal_keys(proposal: ActionProposal) -> set[tuple[str, str]]:
    derived, _ = describe_proposal(proposal.action_type, proposal.payload)
    return _resource_keys(proposal.affected_resources) | _resource_keys(
        cast(list[dict[str, Any]], derived)
    )


async def _root_open_proposals(
    session: AsyncSession, run: AgentRun
) -> list[tuple[str, ActionProposal]]:
    rows = await session.execute(
        select(AgentStep.run_id, ActionProposal)
        .join(ActionProposal, ActionProposal.id == AgentStep.action_proposal_id)
        .where(
            AgentStep.tenant_id == run.tenant_id,
            ActionProposal.tenant_id == run.tenant_id,
            ActionProposal.status.in_(OPEN_PROPOSAL_STATUSES),
            AgentStep.run_id.in_(
                select(AgentRun.id).where(
                    AgentRun.tenant_id == run.tenant_id,
                    AgentRun.root_run_id == run.root_run_id,
                )
            ),
        )
    )
    return [(run_id, proposal) for run_id, proposal in rows.all()]


async def _do_propose(
    session: AsyncSession,
    context: RequestContext,
    run: AgentRun,
    agent: Agent,
    raw: dict[str, Any],
    payload: AgentStepCreate,
) -> _Outcome:
    if "propose" not in agent.allowed_capabilities:
        return _denial("capability_missing", "The agent is not allowed to propose actions.")
    request = _parse(ActionProposalCreate, raw, "propose")
    if request.action_type not in agent.allowed_actions:
        return _denial(
            "action_not_allowed",
            f"Action {request.action_type} is outside the agent's registered tools.",
        )
    definition = ACTION_REGISTRY[request.action_type]
    if RISK_ORDER[definition.risk_level] > RISK_ORDER[agent.risk_ceiling]:
        return _denial(
            "risk_above_ceiling",
            f"Action {request.action_type} is {definition.risk_level} risk, above the ceiling.",
        )
    derived = agent_context(agent, context)
    if definition.required_permission not in derived.permissions:
        return _denial(
            "owner_lacks_permission",
            f"The run owner lacks {definition.required_permission.value}, so the agent cannot "
            "propose this action.",
        )
    refs, digest = describe_proposal(request.action_type, request.payload)
    # Derived refs always count; caller-supplied ones can only add to them, never hide them.
    new_keys = _resource_keys(cast(list[dict[str, Any]], refs)) | _resource_keys(
        cast(list[dict[str, Any]], request.affected_resources)
    )
    open_proposals = await _root_open_proposals(session, run)
    for _, proposal in open_proposals:
        if proposal.request_hash == digest:
            return _Outcome(
                action_proposal_id=proposal.id,
                output={"deduplicated": True, "action_proposal_id": proposal.id},
            )
    if run.side_effects_used + 1 > run.side_effect_budget:
        return _budget_exhausted("side-effect")
    conflicts = [
        (run_id, proposal)
        for run_id, proposal in open_proposals
        if run_id != run.id and new_keys & _proposal_keys(proposal)
    ]
    if conflicts:
        return _Outcome(
            status="escalated",
            error_code="conflicting_outputs",
            output={"detail": "A different run already proposed a change to the same resource."},
            escalation=_Escalation(
                reason="conflicting_outputs",
                summary="Two agent runs proposed different changes to the same resource.",
                evidence=[
                    {"action_proposal_id": proposal.id, "run_id": run_id}
                    for run_id, proposal in conflicts
                ],
                next_steps=["Pick one proposal or revise the objective, then resume the runs."],
                also_runs=sorted({run_id for run_id, _ in conflicts}),
            ),
        )
    # Not committed here: the proposal, its step and the budget spend commit together, so a
    # step that loses the run-version race leaves no orphan proposal behind.
    proposal = await create_proposal(
        session, derived, request, f"agent:{run.id}:{payload.step_key}", commit=False
    )
    return _Outcome(
        action_proposal_id=proposal.id,
        side_effects=1,
        output={"action_proposal_id": proposal.id, "status": proposal.status},
    )
