import hashlib
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import uuid4

from pydantic import BaseModel, ValidationError
from sqlalchemy import ColumnElement, func, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..actions.registry import ACTION_REGISTRY
from ..actions.service import create_proposal, describe_proposal
from ..api.deps import RequestContext
from ..audit import record_audit, record_outbox_event
from ..config import settings
from ..domain import (
    ConflictError,
    InvalidRequestError,
    InvalidTransitionError,
    NotFoundError,
    PermissionDeniedError,
    PreconditionRequiredError,
    VersionConflictError,
    normalize_name,
)
from ..flags import require_capability
from ..knowledge.retrieval import assemble_context
from ..models import (
    ActionProposal,
    Agent,
    AgentMessage,
    AgentRun,
    AgentStep,
    WorkItem,
    utc_now,
)
from ..pagination import page_statement
from ..permissions import Permission
from ..schemas import (
    ActionProposalCreate,
    AgentRunCreate,
    AgentRunRead,
    AgentStepCreate,
    AgentStepRead,
    AgentStepResult,
    DelegationInput,
    EscalationInput,
    KnowledgeContextRequest,
    OutputInput,
    WorkItemCreate,
)
from ..work.items import create_work_item_in_session
from .domain import (
    ACTIVE_RUN_STATUSES,
    FAILED_RUN_STATUSES,
    OPEN_PROPOSAL_STATUSES,
    RISK_ORDER,
    TERMINAL_RUN_STATUSES,
    validate_run_transition,
)

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


async def _terminate(
    session: AsyncSession,
    context: RequestContext,
    run: AgentRun,
    status: str,
    reason: str,
    *,
    extra_values: dict[str, Any] | None = None,
    notify_parent: bool = True,
) -> None:
    validate_run_transition(run.status, status)
    await _update_run(
        session,
        run,
        status=status,
        terminal_reason=reason,
        completed_at=utc_now(),
        **(extra_values or {}),
    )
    await _audit_run(session, context, run, f"agent.run.{status}", reason=reason)
    if status in {"cancelled", "failed"}:
        await _stop_descendants(
            session, context, run, "parent_cancelled" if status == "cancelled" else "parent_failed"
        )
    if notify_parent and run.parent_run_id:
        session.add(
            AgentMessage(
                tenant_id=run.tenant_id,
                root_run_id=run.root_run_id,
                from_run_id=run.id,
                to_run_id=run.parent_run_id,
                kind="result",
                body={"status": status, "reason": reason, "objective": run.objective},
            )
        )


@dataclass
class _Escalation:
    reason: str
    summary: str
    evidence: list[dict[str, Any]] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)
    run_status: str = "waiting_human"
    also_runs: list[str] = field(default_factory=list)


async def _escalate(
    session: AsyncSession,
    context: RequestContext,
    run: AgentRun,
    spec: _Escalation,
    *,
    step: AgentStep | None = None,
    extra_values: dict[str, Any] | None = None,
) -> WorkItem:
    """Hand the run to a human: a work item carrying the evidence, and a persisted message."""
    lines = [
        spec.summary,
        f"Agent: {run.agent_key} {run.agent_version}; run {run.id}; objective: {run.objective}",
    ]
    if step is not None:
        lines.append(f"Step: {step.id} ({step.step_type})")
    if spec.next_steps:
        lines.append("Proposed next steps: " + "; ".join(spec.next_steps))
    if spec.evidence:
        lines.append("Evidence: " + json.dumps(spec.evidence, default=str)[:4000])
    item = await create_work_item_in_session(
        session,
        context,
        WorkItemCreate(
            item_type="escalation",
            title=f"Agent escalation ({spec.reason}): {run.objective}"[:200],
            description="\n".join(lines)[:10000],
            priority=80,
            owner_id=run.owner_id,
            assignee_id=run.owner_id,
            source="agent.escalation",
        ),
    )
    terminal = spec.run_status in TERMINAL_RUN_STATUSES
    validate_run_transition(run.status, spec.run_status)
    await _update_run(
        session,
        run,
        status=spec.run_status,
        escalation_work_item_id=item.id,
        escalation_reason=spec.reason,
        terminal_reason=spec.reason if terminal else None,
        completed_at=utc_now() if terminal else None,
        **(extra_values or {}),
    )
    if terminal and run.parent_run_id:
        session.add(
            AgentMessage(
                tenant_id=run.tenant_id,
                root_run_id=run.root_run_id,
                from_run_id=run.id,
                to_run_id=run.parent_run_id,
                kind="result",
                body={"status": spec.run_status, "reason": spec.reason, "objective": run.objective},
            )
        )
    session.add(
        AgentMessage(
            tenant_id=run.tenant_id,
            root_run_id=run.root_run_id,
            from_run_id=run.id,
            to_run_id=None,
            kind="escalation",
            body={
                "reason": spec.reason,
                "work_item_id": item.id,
                "summary": spec.summary,
                "step_id": step.id if step else None,
            },
        )
    )
    await _audit_run(
        session, context, run, "agent.run.escalated", reason=spec.reason, work_item_id=item.id
    )
    if terminal:
        await _stop_descendants(session, context, run, "parent_" + spec.run_status)
    for other_id in spec.also_runs:
        other = await session.scalar(
            select(AgentRun).where(
                AgentRun.id == other_id,
                AgentRun.tenant_id == run.tenant_id,
                AgentRun.status.in_({"running", "paused"}),
            )
        )
        if other is not None:
            await _update_run(
                session,
                other,
                status="waiting_human",
                escalation_work_item_id=item.id,
                escalation_reason=spec.reason,
            )
            await _audit_run(
                session, context, other, "agent.run.escalated",
                reason=spec.reason, work_item_id=item.id,
            )
    return item


async def start_run(
    session: AsyncSession,
    context: RequestContext,
    payload: AgentRunCreate,
    idempotency_key: str,
) -> AgentRun:
    if not idempotency_key.strip():
        raise InvalidRequestError("Idempotency-Key header is required")
    await require_capability(session, context, "agents", operation="agent.run.start")
    if idempotency_key.startswith("delegate:"):
        raise InvalidRequestError("Idempotency-Key prefix 'delegate:' is reserved")
    request_hash = _digest(payload.model_dump(mode="json"))
    existing = await session.scalar(
        select(AgentRun).where(
            AgentRun.tenant_id == context.tenant_id,
            AgentRun.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.owner_id != context.actor_id:
            raise ConflictError("Idempotency-Key was reused for a different agent run")
        if existing.request_hash != request_hash:
            raise ConflictError("Idempotency-Key was reused for a different agent run")
        return existing
    agent = await _get_agent(session, context.tenant_id, payload.agent_id)
    if agent is None:
        raise NotFoundError("Agent not found")
    if agent.status != "active":
        raise ConflictError(f"Agent is {agent.status} and cannot start runs")
    if payload.deadline_at.tzinfo is None:
        raise InvalidRequestError("deadline_at must include a timezone")
    now = utc_now()
    deadline = _aware(payload.deadline_at)
    if deadline <= now:
        raise InvalidRequestError("deadline_at must be in the future")
    if deadline > now + timedelta(hours=settings.agent_max_run_hours):
        raise InvalidRequestError(
            f"deadline_at is more than {settings.agent_max_run_hours} hours away"
        )
    budgets = {
        "token_budget": payload.token_budget or agent.token_budget,
        "step_budget": payload.step_budget or agent.step_budget,
        "side_effect_budget": (
            agent.side_effect_budget
            if payload.side_effect_budget is None
            else payload.side_effect_budget
        ),
    }
    caps = {
        "token_budget": settings.agent_token_budget_cap,
        "step_budget": settings.agent_step_budget_cap,
        "side_effect_budget": settings.agent_side_effect_budget_cap,
    }
    for name, value in budgets.items():
        if value > getattr(agent, name):
            raise InvalidRequestError(f"{name} exceeds the agent's registered limit")
        if value > caps[name]:
            raise InvalidRequestError(f"{name} exceeds the platform cap of {caps[name]}")
    if payload.work_item_id is not None:
        found = await session.scalar(
            select(WorkItem.id).where(
                WorkItem.id == payload.work_item_id, WorkItem.tenant_id == context.tenant_id
            )
        )
        if found is None:
            raise InvalidRequestError("Unknown work_item_id")
    run_id = str(uuid4())
    run = AgentRun(
        id=run_id,
        tenant_id=context.tenant_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        agent_id=agent.id,
        agent_key=agent.key,
        agent_version=agent.agent_version,
        root_run_id=run_id,
        depth=0,
        max_depth=min(agent.max_depth, settings.agent_max_depth_cap),
        max_fanout=min(agent.max_fanout, settings.agent_max_fanout_cap),
        owner_id=context.actor_id,
        objective=payload.objective,
        objective_hash=_digest(normalize_name(payload.objective)),
        expected_result=payload.expected_result,
        deadline_at=deadline,
        work_item_id=payload.work_item_id,
        status="running",
        trace_id=context.trace_id,
        **budgets,
    )
    session.add(run)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        winner = await session.scalar(
            select(AgentRun).where(
                AgentRun.tenant_id == context.tenant_id,
                AgentRun.idempotency_key == idempotency_key,
            )
        )
        if (
            winner is None
            or winner.request_hash != request_hash
            or winner.owner_id != context.actor_id
        ):
            raise ConflictError("Idempotency-Key was reused for a different agent run") from None
        return winner
    await _audit_run(session, context, run, "agent.run.started", work_item_id=run.work_item_id)
    await session.commit()
    await session.refresh(run)
    return run


async def list_runs(
    session: AsyncSession,
    context: RequestContext,
    *,
    limit: int,
    offset: int,
    cursor: str | None,
    status: str | None = None,
    agent_id: str | None = None,
    root_run_id: str | None = None,
) -> list[AgentRun]:
    statement = select(AgentRun).where(AgentRun.tenant_id == context.tenant_id)
    if status:
        statement = statement.where(AgentRun.status == status)
    if agent_id:
        statement = statement.where(AgentRun.agent_id == agent_id)
    if root_run_id:
        statement = statement.where(AgentRun.root_run_id == root_run_id)
    return list(await session.scalars(page_statement(statement, AgentRun, limit, offset, cursor)))


async def list_steps(
    session: AsyncSession, context: RequestContext, run_id: str
) -> list[AgentStep]:
    run = await get_run(session, context, run_id)
    return list(
        await session.scalars(
            select(AgentStep)
            .where(AgentStep.tenant_id == context.tenant_id, AgentStep.run_id == run.id)
            .order_by(AgentStep.seq)
        )
    )


async def list_messages(
    session: AsyncSession, context: RequestContext, run_id: str
) -> list[AgentMessage]:
    run = await get_run(session, context, run_id)
    return list(
        await session.scalars(
            select(AgentMessage)
            .where(
                AgentMessage.tenant_id == context.tenant_id,
                AgentMessage.root_run_id == run.root_run_id,
                (AgentMessage.from_run_id == run.id) | (AgentMessage.to_run_id == run.id),
            )
            .order_by(AgentMessage.created_at, AgentMessage.id)
        )
    )


def _check_not_overdue(run: AgentRun) -> None:
    if _aware(run.deadline_at) <= utc_now():
        raise ConflictError("Agent run deadline has passed")


async def transition_run(
    session: AsyncSession,
    context: RequestContext,
    run_id: str,
    action: str,
    expected_version: int | None,
) -> AgentRun:
    if expected_version is None:
        raise PreconditionRequiredError("If-Match header is required")
    run = await get_run(session, context, run_id)
    _authorize(context, run, allow_manage=True)
    if run.version != expected_version:
        raise VersionConflictError("record_version_conflict")
    if action == "pause":
        validate_run_transition(run.status, "paused")
        await _update_run(session, run, status="paused")
        await _audit_run(session, context, run, "agent.run.paused")
    elif action == "resume":
        await require_capability(session, context, "agents", operation="agent.run.resume")
        validate_run_transition(run.status, "running")
        agent = await _get_agent(session, run.tenant_id, run.agent_id)
        if agent is None or agent.status != "active":
            raise ConflictError("Agent is not active")
        _check_not_overdue(run)
        if run.status == "waiting_human":
            item = await session.scalar(
                select(WorkItem).where(
                    WorkItem.id == run.escalation_work_item_id,
                    WorkItem.tenant_id == run.tenant_id,
                )
            )
            if item is None or item.status != "completed":
                raise ConflictError("The escalation work item must be completed before resuming")
        await _update_run(
            session,
            run,
            status="running",
            escalation_work_item_id=None,
            escalation_reason=None,
        )
        await _audit_run(session, context, run, "agent.run.resumed")
    elif action == "cancel":
        await _cancel_tree(session, context, run)
    else:
        raise InvalidRequestError(f"Unsupported run action: {action}")
    await session.commit()
    await session.refresh(run)
    return run


async def _active_descendants(session: AsyncSession, run: AgentRun) -> list[AgentRun]:
    # Walk every run in the tree: an active grandchild can sit below a finished child.
    tree = list(
        await session.scalars(
            select(AgentRun).where(
                AgentRun.tenant_id == run.tenant_id,
                AgentRun.root_run_id == run.root_run_id,
            )
        )
    )
    doomed = {run.id}
    grew = True
    while grew:
        grew = False
        for candidate in tree:
            if candidate.parent_run_id in doomed and candidate.id not in doomed:
                doomed.add(candidate.id)
                grew = True
    return [
        candidate
        for candidate in tree
        if candidate.id in doomed
        and candidate.id != run.id
        and candidate.status in ACTIVE_RUN_STATUSES
    ]


async def _stop_descendants(
    session: AsyncSession, context: RequestContext, run: AgentRun, reason: str
) -> None:
    for descendant in await _active_descendants(session, run):
        if descendant.status not in ACTIVE_RUN_STATUSES:
            continue  # already stopped by an earlier cascade in this loop
        await _terminate(
            session, context, descendant, "cancelled", reason, notify_parent=False
        )


async def _cancel_tree(session: AsyncSession, context: RequestContext, run: AgentRun) -> None:
    validate_run_transition(run.status, "cancelled")
    await _terminate(session, context, run, "cancelled", "cancelled_by_user")


def overdue_run_condition(now: datetime) -> ColumnElement[bool]:
    """Active runs past their deadline. Shared by the sweep and the worker's discovery."""
    return AgentRun.status.in_(ACTIVE_RUN_STATUSES) & (AgentRun.deadline_at <= now)


async def expire_overdue_runs(session: AsyncSession, context: RequestContext) -> int:
    """Fail runs past their deadline so a crashed or stalled driver can never strand one."""
    runs = list(
        await session.scalars(
            select(AgentRun).where(
                AgentRun.tenant_id == context.tenant_id, overdue_run_condition(utc_now())
            )
        )
    )
    expired = 0
    for candidate in runs:
        run_id = candidate.id
        try:
            run = await session.get_one(AgentRun, run_id)
            if run.status == "waiting_human":
                await _terminate(session, context, run, "failed", "deadline_exceeded")
            else:
                await _escalate(
                    session,
                    context,
                    run,
                    _Escalation(
                        reason="deadline_exceeded",
                        summary="The run passed its deadline before reaching a terminal state.",
                        next_steps=["Review partial results and re-run or close the objective."],
                        run_status="failed",
                    ),
                )
            await session.commit()
            expired += 1
        except Exception:
            await session.rollback()
            logger.exception("could not expire agent run %s", run_id)
    return expired


# --------------------------------------------------------------------------- steps


@dataclass
class _Outcome:
    status: str = "completed"
    output: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None
    action_proposal_id: str | None = None
    child_run_id: str | None = None
    context_assembly_id: str | None = None
    side_effects: int = 0
    token_reserve: int = 0
    charge: bool = True
    escalation: _Escalation | None = None
    run_status: str | None = None
    terminal_reason: str | None = None
    reject: str | None = None


def _denial(code: str, summary: str) -> _Outcome:
    return _Outcome(
        status="escalated",
        error_code=code,
        output={"detail": summary},
        escalation=_Escalation(
            reason="policy_denial",
            summary=summary,
            evidence=[{"code": code}],
            next_steps=["Decide whether the agent's registered scope should change."],
        ),
    )


def _budget_exhausted(what: str) -> _Outcome:
    return _Outcome(
        status="escalated",
        error_code="budget_exhausted",
        output={"detail": f"{what} budget exhausted"},
        charge=False,
        escalation=_Escalation(
            reason="budget_exhausted",
            summary=f"The run exhausted its {what} budget.",
            next_steps=["Review the partial results and start a new run with a larger budget."],
            run_status="budget_exhausted",
        ),
    )


def _parse[T: BaseModel](model: type[T], raw: dict[str, Any], step_type: str) -> T:
    try:
        return model.model_validate(raw)
    except ValidationError as error:
        raise InvalidRequestError(f"Invalid {step_type} input: {error}") from error


async def _do_retrieve(
    session: AsyncSession,
    context: RequestContext,
    run: AgentRun,
    agent: Agent,
    raw: dict[str, Any],
    payload: AgentStepCreate,
) -> _Outcome:
    if "read" not in agent.allowed_capabilities:
        return _denial("capability_missing", "The agent is not allowed to read knowledge.")
    request = _parse(KnowledgeContextRequest, raw, "retrieve")
    result = await assemble_context(session, agent_context(agent, context), request)
    return _Outcome(
        context_assembly_id=result.assembly.id,
        output={
            "context_assembly_id": result.assembly.id,
            "insufficient_evidence": result.assembly.insufficient_evidence,
            "citations": [item.citation for item in result.items],
        },
    )


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


async def _ancestor_agent_ids(session: AsyncSession, run: AgentRun) -> set[str]:
    chain = {run.agent_id}
    current = run
    while current.parent_run_id:
        parent = await session.scalar(
            select(AgentRun).where(
                AgentRun.id == current.parent_run_id, AgentRun.tenant_id == run.tenant_id
            )
        )
        if parent is None:
            break
        chain.add(parent.agent_id)
        current = parent
    return chain


async def _consecutive_failures(session: AsyncSession, run: AgentRun, agent_id: str) -> int:
    statuses = await session.scalars(
        select(AgentRun.status)
        .where(
            AgentRun.tenant_id == run.tenant_id,
            AgentRun.root_run_id == run.root_run_id,
            AgentRun.agent_id == agent_id,
            AgentRun.status.in_(TERMINAL_RUN_STATUSES),
        )
        .order_by(AgentRun.completed_at.desc(), AgentRun.id.desc())
        .limit(settings.agent_repeated_failure_threshold)
    )
    count = 0
    for status in statuses:
        if status not in FAILED_RUN_STATUSES:
            break
        count += 1
    return count


def _reject(code: str, detail: str) -> _Outcome:
    return _Outcome(status="rejected", error_code=code, reject=detail, output={"detail": detail})


async def _do_delegate(
    session: AsyncSession,
    context: RequestContext,
    run: AgentRun,
    agent: Agent,
    raw: dict[str, Any],
    payload: AgentStepCreate,
) -> _Outcome:
    if "delegate" not in agent.allowed_capabilities:
        return _denial("capability_missing", "The agent is not allowed to delegate.")
    request = _parse(DelegationInput, raw, "delegate")
    target = await session.scalar(
        select(Agent).where(Agent.tenant_id == run.tenant_id, Agent.key == request.agent_key)
    )
    if target is None:
        raise NotFoundError("Target agent not found")
    if target.status != "active":
        return _reject("target_agent_inactive", f"Target agent is {target.status}")
    if target.id in await _ancestor_agent_ids(session, run):
        return _reject("delegation_cycle", "Delegation would revisit an agent already in the chain")
    if run.depth + 1 > run.max_depth:
        return _reject("max_depth_exceeded", f"Delegation depth is limited to {run.max_depth}")
    fanout = await session.scalar(
        select(func.count())
        .select_from(AgentRun)
        .where(AgentRun.tenant_id == run.tenant_id, AgentRun.parent_run_id == run.id)
    )
    if (fanout or 0) >= run.max_fanout:
        return _reject("max_fanout_exceeded", f"Fan-out is limited to {run.max_fanout}")
    objective_hash = _digest(normalize_name(request.objective))
    duplicate = await session.scalar(
        select(AgentRun.id).where(
            AgentRun.tenant_id == run.tenant_id,
            AgentRun.root_run_id == run.root_run_id,
            AgentRun.objective_hash == objective_hash,
            AgentRun.status.in_(ACTIVE_RUN_STATUSES),
        )
    )
    if duplicate is not None:
        return _reject("duplicate_ownership", "Another active run already owns this objective")
    if request.deadline_at.tzinfo is None:
        raise InvalidRequestError("deadline_at must include a timezone")
    deadline = _aware(request.deadline_at)
    if deadline <= utc_now() or deadline > _aware(run.deadline_at):
        return _reject(
            "invalid_deadline", "Child deadline must be in the future and within the parent's"
        )
    if (
        request.token_budget > target.token_budget
        or request.step_budget > target.step_budget
        or request.side_effect_budget > target.side_effect_budget
    ):
        return _reject("exceeds_target_agent_limits", "Budget exceeds the target agent's limits")
    if request.token_budget > run.token_budget - run.tokens_used - payload.tokens:
        return _reject("insufficient_token_budget", "Parent has too few tokens left to carve out")
    if request.side_effect_budget > run.side_effect_budget - run.side_effects_used:
        return _reject(
            "insufficient_side_effect_budget", "Parent has too few side effects left to carve out"
        )
    if (
        await _consecutive_failures(session, run, target.id)
        >= settings.agent_repeated_failure_threshold
    ):
        return _Outcome(
            status="escalated",
            error_code="repeated_failure",
            output={"detail": "Target agent keeps failing under this root run."},
            escalation=_Escalation(
                reason="repeated_failure",
                summary=f"Agent {target.key} failed repeatedly on delegated work.",
                evidence=[{"agent_key": target.key}],
                next_steps=["Investigate the agent or take over the objective manually."],
            ),
        )
    child_id = str(uuid4())
    child = AgentRun(
        id=child_id,
        tenant_id=run.tenant_id,
        idempotency_key=f"delegate:{run.id}:{payload.step_key}",
        request_hash=_digest(raw),
        agent_id=target.id,
        agent_key=target.key,
        agent_version=target.agent_version,
        parent_run_id=run.id,
        root_run_id=run.root_run_id,
        depth=run.depth + 1,
        max_depth=min(run.max_depth, target.max_depth),
        max_fanout=min(target.max_fanout, settings.agent_max_fanout_cap),
        owner_id=run.owner_id,
        objective=request.objective.strip(),
        objective_hash=objective_hash,
        expected_result=request.expected_result,
        deadline_at=deadline,
        work_item_id=run.work_item_id,
        token_budget=request.token_budget,
        step_budget=request.step_budget,
        side_effect_budget=request.side_effect_budget,
        status="running",
        trace_id=context.trace_id,
    )
    session.add(child)
    await session.flush()
    session.add(
        AgentMessage(
            tenant_id=run.tenant_id,
            root_run_id=run.root_run_id,
            from_run_id=run.id,
            to_run_id=child.id,
            kind="delegation",
            body={
                "reason": request.reason,
                "objective": child.objective,
                "expected_result": request.expected_result,
                "deadline_at": deadline.isoformat(),
                "token_budget": request.token_budget,
                "step_budget": request.step_budget,
                "side_effect_budget": request.side_effect_budget,
            },
        )
    )
    await _audit_run(
        session, context, child, "agent.run.started", parent_run_id=run.id, depth=child.depth
    )
    return _Outcome(
        child_run_id=child.id,
        token_reserve=request.token_budget,
        side_effects=request.side_effect_budget,
        output={"child_run_id": child.id, "agent_key": target.key, "depth": child.depth},
    )


async def _do_escalate(
    session: AsyncSession,
    context: RequestContext,
    run: AgentRun,
    agent: Agent,
    raw: dict[str, Any],
    payload: AgentStepCreate,
) -> _Outcome:
    request = _parse(EscalationInput, raw, "escalate")
    if "escalate" not in agent.allowed_capabilities:
        return _denial("capability_missing", "The agent is not allowed to escalate on its own.")
    return _Outcome(
        status="escalated",
        output={"reason": request.reason},
        escalation=_Escalation(
            reason=request.reason,
            summary=request.summary,
            evidence=request.evidence_refs,
            next_steps=request.proposed_next_steps,
        ),
    )


async def _do_output(
    session: AsyncSession,
    context: RequestContext,
    run: AgentRun,
    agent: Agent,
    raw: dict[str, Any],
    payload: AgentStepCreate,
) -> _Outcome:
    request = _parse(OutputInput, raw, "output")
    if request.outcome == "success":
        open_children = await session.scalar(
            select(func.count())
            .select_from(AgentRun)
            .where(
                AgentRun.tenant_id == run.tenant_id,
                AgentRun.parent_run_id == run.id,
                AgentRun.status.in_(ACTIVE_RUN_STATUSES),
            )
        )
        if open_children:
            return _reject("children_active", "Delegated runs are still active")
    failed = request.outcome == "failed"
    return _Outcome(
        output={"outcome": request.outcome, "summary": request.summary, "result": request.result},
        run_status="failed" if failed else "completed",
        terminal_reason="agent_reported_failure" if failed else "completed",
    )


_Handler = Callable[
    [AsyncSession, RequestContext, AgentRun, Agent, dict[str, Any], AgentStepCreate],
    Awaitable[_Outcome],
]
_HANDLERS: dict[str, _Handler] = {
    "retrieve": _do_retrieve,
    "propose": _do_propose,
    "delegate": _do_delegate,
    "escalate": _do_escalate,
    "output": _do_output,
}


async def submit_step(
    session: AsyncSession,
    context: RequestContext,
    run_id: str,
    payload: AgentStepCreate,
) -> AgentStepResult:
    run = await get_run(session, context, run_id)
    _authorize(context, run, allow_manage=False)
    request_hash = _digest(payload.step_type, payload.input, payload.tokens)
    existing = await session.scalar(
        select(AgentStep).where(
            AgentStep.run_id == run.id,
            AgentStep.tenant_id == run.tenant_id,
            AgentStep.step_key == payload.step_key,
        )
    )
    if existing is not None:
        if existing.request_hash != request_hash:
            raise ConflictError("step_key was reused for a different step")
        if existing.status == "rejected":
            raise ConflictError(str(existing.output.get("detail", "Step was rejected")))
        return AgentStepResult(
            step=AgentStepRead.model_validate(existing), run=AgentRunRead.model_validate(run)
        )
    await require_capability(session, context, "agents", operation="agent.step")
    if run.status != "running":
        raise InvalidTransitionError(f"Agent run is {run.status}; steps need a running run")
    agent = await _get_agent(session, run.tenant_id, run.agent_id)
    if agent is None or agent.status != "active":
        raise ConflictError("Agent is not active")
    if _aware(run.deadline_at) <= utc_now():
        await _escalate(
            session,
            context,
            run,
            _Escalation(
                reason="deadline_exceeded",
                summary="The run passed its deadline before reaching a terminal state.",
                run_status="failed",
            ),
        )
        await session.commit()
        raise ConflictError("Agent run deadline has passed")

    if run.steps_used >= run.step_budget:
        outcome = _budget_exhausted("step")
    elif run.tokens_used + payload.tokens > run.token_budget:
        outcome = _budget_exhausted("token")
    else:
        outcome = await _HANDLERS[payload.step_type](
            session, context, run, agent, payload.input, payload
        )

    step = AgentStep(
        tenant_id=run.tenant_id,
        run_id=run.id,
        seq=run.steps_used + 1,
        step_key=payload.step_key,
        request_hash=request_hash,
        step_type=payload.step_type,
        status=outcome.status,
        input=payload.input,
        output=outcome.output,
        action_proposal_id=outcome.action_proposal_id,
        child_run_id=outcome.child_run_id,
        context_assembly_id=outcome.context_assembly_id,
        tokens=payload.tokens if outcome.charge else 0,
        error_code=outcome.error_code,
    )
    session.add(step)
    try:
        await session.flush()
    except IntegrityError as error:
        await session.rollback()
        raise VersionConflictError("record_version_conflict") from error
    spent = payload.tokens if outcome.charge else 0
    counters = {
        "steps_used": run.steps_used + 1,
        "tokens_used": run.tokens_used + spent + outcome.token_reserve,
        "side_effects_used": run.side_effects_used + outcome.side_effects,
    }
    if outcome.escalation is not None:
        await _escalate(
            session, context, run, outcome.escalation, step=step, extra_values=counters
        )
    elif outcome.run_status is not None:
        await _terminate(
            session,
            context,
            run,
            outcome.run_status,
            outcome.terminal_reason or outcome.run_status,
            extra_values=counters,
        )
    else:
        await _update_run(session, run, **counters)
    succeeded = outcome.error_code is None
    await record_audit(
        session,
        context,
        "agent.step.recorded" if succeeded else "agent.step.denied",
        "agent_step",
        step.id,
        outcome="success" if succeeded else "denied",
        reason=outcome.error_code,
        details=_run_details(
            run,
            step_type=step.step_type,
            step_status=step.status,
            action_proposal_id=step.action_proposal_id,
            child_run_id=step.child_run_id,
        ),
    )
    if outcome.reject is not None:
        await session.commit()
        raise ConflictError(outcome.reject)
    await session.commit()
    await session.refresh(run)
    await session.refresh(step)
    return AgentStepResult(
        step=AgentStepRead.model_validate(step), run=AgentRunRead.model_validate(run)
    )
