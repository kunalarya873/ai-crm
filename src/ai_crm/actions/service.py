import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.deps import RequestContext
from ..audit import record_audit, record_outbox_event
from ..config import settings
from ..domain import (
    ConflictError,
    DomainError,
    InvalidRequestError,
    InvalidTransitionError,
    NotFoundError,
    SeparationOfDutiesError,
    VersionConflictError,
)
from ..integrations import (
    ConnectorProviderError,
    connection_is_writable,
    get_connector,
)
from ..models import (
    ActionExecution,
    ActionProposal,
    Activity,
    Contact,
    ExternalWrite,
    IntegrationConnection,
    Opportunity,
    Task,
    WorkItem,
    utc_now,
)
from ..permissions import Permission
from ..schemas import (
    ActionDecision,
    ActionDryRunResponse,
    ActionProposalCreate,
    ActionProposalEdit,
    ActionRecoveryRequest,
    ActivityCreate,
    ContactUpdate,
    TaskCreate,
)
from .registry import (
    ActionDefinition,
    ApprovalRequestAction,
    ContactAssignOwnerAction,
    ContactUpdateAction,
    ExternalActivityAction,
    get_action_definition,
)

PROPOSAL_STATUSES = frozenset(
    {
        "proposed",
        "edited",
        "approved",
        "rejected",
        "expired",
        "revoked",
        "executing",
        "succeeded",
        "failed",
        "recoverable",
    }
)
EXECUTION_STATUSES = frozenset(
    {"executing", "succeeded", "failed", "recoverable", "uncertain", "cancelled"}
)


def _hash_payload(action_type: str, payload: dict[str, object]) -> str:
    encoded = json.dumps(
        {"action_type": action_type, "payload": payload},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(encoded.encode()).hexdigest()


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _json_safe(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def _require_permission(context: RequestContext, permission: Permission) -> None:
    if permission not in context.permissions:
        raise InvalidRequestError(f"Action requires permission: {permission.value}")


async def get_proposal(
    session: AsyncSession,
    context: RequestContext,
    proposal_id: str,
) -> ActionProposal:
    proposal = await session.scalar(
        select(ActionProposal).where(
            ActionProposal.id == proposal_id,
            ActionProposal.tenant_id == context.tenant_id,
        )
    )
    if proposal is None:
        raise NotFoundError("Action proposal not found")
    return proposal


async def get_execution(
    session: AsyncSession,
    context: RequestContext,
    execution_id: str,
) -> ActionExecution:
    execution = await session.scalar(
        select(ActionExecution).where(
            ActionExecution.id == execution_id,
            ActionExecution.tenant_id == context.tenant_id,
        )
    )
    if execution is None:
        raise NotFoundError("Action execution not found")
    return execution


def _expiry(expires_at: datetime | None) -> datetime:
    value = _aware(expires_at)
    if value is None:
        value = utc_now() + timedelta(hours=settings.action_default_expiration_hours)
    if value <= utc_now():
        raise InvalidRequestError("Action proposal expiration must be in the future")
    return value


def _resource_refs(action_type: str, payload: dict[str, object]) -> list[dict[str, object]]:
    keys = {
        "contact_id": "contact",
        "company_id": "company",
        "opportunity_id": "opportunity",
        "connection_id": "integration_connection",
    }
    refs: list[dict[str, object]] = []
    for key, resource_type in keys.items():
        value = payload.get(key)
        if isinstance(value, str) and value:
            refs.append({"resource_type": resource_type, "resource_id": value})
    if action_type == "contact.update" and isinstance(payload.get("contact_id"), str):
        refs.append({"resource_type": "contact", "resource_id": payload["contact_id"]})
    if action_type == "contact.assign_owner" and isinstance(payload.get("contact_id"), str):
        refs.append({"resource_type": "contact", "resource_id": payload["contact_id"]})
    return list({json.dumps(item, sort_keys=True): item for item in refs}.values())


def describe_proposal(
    action_type: str, payload: dict[str, object]
) -> tuple[list[dict[str, object]], str]:
    """Affected-resource refs and request hash a proposal of this shape would get."""
    definition = get_action_definition(action_type)
    normalized = definition.validate(payload).model_dump(mode="json", exclude_unset=True)
    return _resource_refs(action_type, normalized), _hash_payload(action_type, normalized)


def _side_effects(definition: ActionDefinition, supplied: list[str]) -> list[str]:
    return supplied or list(definition.expected_side_effects)


async def _validate_source_ai_run(
    session: AsyncSession,
    context: RequestContext,
    source_ai_run_id: str | None,
) -> None:
    if source_ai_run_id is None:
        return
    from ..models import AIRun

    run = await session.scalar(
        select(AIRun).where(
            AIRun.id == source_ai_run_id,
            AIRun.tenant_id == context.tenant_id,
        )
    )
    if run is None:
        raise NotFoundError("Source AI run not found")
    if run.status not in {"succeeded", "fallback"}:
        raise ConflictError("Only completed AI runs can source an action proposal")


async def create_proposal(
    session: AsyncSession,
    context: RequestContext,
    payload: ActionProposalCreate,
    idempotency_key: str,
    *,
    commit: bool = True,
) -> ActionProposal:
    _require_permission(context, Permission.ACTIONS_PROPOSE)
    if not idempotency_key.strip():
        raise InvalidRequestError("Idempotency-Key header is required")
    definition = get_action_definition(payload.action_type)
    _require_permission(context, definition.required_permission)
    normalized = definition.validate(payload.payload)
    normalized_payload = normalized.model_dump(mode="json", exclude_unset=True)
    request_digest = _hash_payload(definition.action_type, normalized_payload)
    existing = await session.scalar(
        select(ActionProposal).where(
            ActionProposal.tenant_id == context.tenant_id,
            ActionProposal.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_hash != request_digest:
            raise ConflictError("Idempotency-Key was reused for a different action proposal")
        return existing
    await _validate_source_ai_run(session, context, payload.source_ai_run_id)
    proposal = ActionProposal(
        tenant_id=context.tenant_id,
        idempotency_key=idempotency_key,
        request_hash=request_digest,
        action_type=definition.action_type,
        action_version=definition.version,
        required_permission=definition.required_permission.value,
        risk_level=definition.risk_level,
        requires_approval=definition.requires_approval,
        status="proposed",
        payload=normalized_payload,
        evidence_refs=payload.evidence_refs,
        affected_resources=payload.affected_resources or _resource_refs(
            definition.action_type, normalized_payload
        ),
        intended_changes=payload.intended_changes or normalized_payload,
        expected_side_effects=_side_effects(definition, payload.expected_side_effects),
        source_ai_run_id=payload.source_ai_run_id,
        requested_by=context.actor_id,
        expires_at=_expiry(payload.expires_at),
    )
    session.add(proposal)
    await session.flush()
    await record_audit(
        session,
        context,
        "action.proposal.created",
        "action_proposal",
        proposal.id,
        details={"action_type": proposal.action_type, "risk_level": proposal.risk_level},
    )
    await record_outbox_event(
        session,
        context,
        "action.proposal.created",
        "action_proposal",
        proposal.id,
        {"action_type": proposal.action_type, "status": proposal.status},
    )
    if commit:
        await session.commit()
        await session.refresh(proposal)
    return proposal


async def list_proposals(
    session: AsyncSession,
    context: RequestContext,
    *,
    limit: int,
    offset: int,
    action_type: str | None = None,
    proposal_status: str | None = None,
) -> list[ActionProposal]:
    statement = select(ActionProposal).where(ActionProposal.tenant_id == context.tenant_id)
    if action_type:
        statement = statement.where(ActionProposal.action_type == action_type)
    if proposal_status:
        if proposal_status not in PROPOSAL_STATUSES:
            raise InvalidRequestError(f"Unsupported proposal status: {proposal_status}")
        statement = statement.where(ActionProposal.status == proposal_status)
    result = await session.scalars(
        statement.order_by(ActionProposal.created_at.desc()).offset(offset).limit(limit)
    )
    return list(result)


async def list_executions(
    session: AsyncSession,
    context: RequestContext,
    *,
    limit: int,
    offset: int,
    execution_status: str | None = None,
) -> list[ActionExecution]:
    statement = select(ActionExecution).where(ActionExecution.tenant_id == context.tenant_id)
    if execution_status:
        if execution_status not in EXECUTION_STATUSES:
            raise InvalidRequestError(f"Unsupported execution status: {execution_status}")
        statement = statement.where(ActionExecution.status == execution_status)
    result = await session.scalars(
        statement.order_by(ActionExecution.created_at.desc()).offset(offset).limit(limit)
    )
    return list(result)


async def approve_proposal(
    session: AsyncSession,
    context: RequestContext,
    proposal_id: str,
    expected_version: int | None,
    decision: ActionDecision,
) -> ActionProposal:
    _require_permission(context, Permission.ACTIONS_APPROVE)
    proposal = await get_proposal(session, context, proposal_id)
    _check_version(proposal, expected_version)
    _ensure_not_expired(proposal)
    if proposal.status not in {"proposed", "edited"}:
        raise InvalidTransitionError(f"Cannot approve proposal in state {proposal.status}")
    if context.actor_id in {proposal.requested_by, proposal.last_edited_by}:
        await record_audit(
            session,
            context,
            "action.proposal.approve",
            "action_proposal",
            proposal.id,
            outcome="denied",
            reason="self_approval",
        )
        await session.commit()
        raise SeparationOfDutiesError(
            "Proposals cannot be approved by their requester or last editor"
        )
    definition = get_action_definition(proposal.action_type)
    _require_permission(context, definition.required_permission)
    definition.validate(proposal.payload)
    proposal.status = "approved"
    proposal.approved_by = context.actor_id
    proposal.approved_at = utc_now()
    proposal.decision_reason = decision.reason
    proposal.version += 1
    proposal.updated_at = utc_now()
    await _proposal_event(session, context, proposal, "action.proposal.approved", decision.reason)
    await session.commit()
    await session.refresh(proposal)
    return proposal


async def reject_proposal(
    session: AsyncSession,
    context: RequestContext,
    proposal_id: str,
    expected_version: int | None,
    decision: ActionDecision,
) -> ActionProposal:
    _require_permission(context, Permission.ACTIONS_APPROVE)
    proposal = await get_proposal(session, context, proposal_id)
    _check_version(proposal, expected_version)
    if proposal.status not in {"proposed", "edited", "approved"}:
        raise InvalidTransitionError(f"Cannot reject proposal in state {proposal.status}")
    proposal.status = "rejected"
    proposal.rejected_by = context.actor_id
    proposal.decision_reason = decision.reason
    proposal.version += 1
    proposal.updated_at = utc_now()
    await _proposal_event(session, context, proposal, "action.proposal.rejected", decision.reason)
    await session.commit()
    await session.refresh(proposal)
    return proposal


async def edit_proposal(
    session: AsyncSession,
    context: RequestContext,
    proposal_id: str,
    expected_version: int | None,
    payload: ActionProposalEdit,
) -> ActionProposal:
    _require_permission(context, Permission.ACTIONS_PROPOSE)
    proposal = await get_proposal(session, context, proposal_id)
    _check_version(proposal, expected_version)
    if proposal.status not in {"proposed", "edited", "approved"}:
        raise InvalidTransitionError(f"Cannot edit proposal in state {proposal.status}")
    definition = get_action_definition(proposal.action_type)
    normalized = definition.validate(payload.payload)
    normalized_payload = normalized.model_dump(mode="json", exclude_unset=True)
    proposal.payload = normalized_payload
    proposal.request_hash = _hash_payload(proposal.action_type, normalized_payload)
    if payload.evidence_refs is not None:
        proposal.evidence_refs = payload.evidence_refs
    if payload.affected_resources is not None:
        proposal.affected_resources = payload.affected_resources
    if payload.intended_changes is not None:
        proposal.intended_changes = payload.intended_changes
    if payload.expected_side_effects is not None:
        proposal.expected_side_effects = payload.expected_side_effects
    if payload.expires_at is not None:
        proposal.expires_at = _expiry(payload.expires_at)
    proposal.status = "edited"
    proposal.last_edited_by = context.actor_id
    proposal.approved_by = None
    proposal.approved_at = None
    proposal.decision_reason = None
    proposal.version += 1
    proposal.updated_at = utc_now()
    await _proposal_event(session, context, proposal, "action.proposal.edited", None)
    await session.commit()
    await session.refresh(proposal)
    return proposal


async def revoke_proposal(
    session: AsyncSession,
    context: RequestContext,
    proposal_id: str,
    expected_version: int | None,
    decision: ActionDecision,
) -> ActionProposal:
    _require_permission(context, Permission.ACTIONS_PROPOSE)
    proposal = await get_proposal(session, context, proposal_id)
    _check_version(proposal, expected_version)
    if proposal.status not in {"proposed", "edited", "approved", "failed", "recoverable"}:
        raise InvalidTransitionError(f"Cannot revoke proposal in state {proposal.status}")
    proposal.status = "revoked"
    proposal.decision_reason = decision.reason
    proposal.version += 1
    proposal.updated_at = utc_now()
    await _proposal_event(session, context, proposal, "action.proposal.revoked", decision.reason)
    await session.commit()
    await session.refresh(proposal)
    return proposal


def _check_version(proposal: ActionProposal, expected_version: int | None) -> None:
    if expected_version is None:
        raise InvalidRequestError("If-Match header is required")
    if proposal.version != expected_version:
        raise VersionConflictError("record_version_conflict")


def _ensure_not_expired(proposal: ActionProposal) -> None:
    expires_at = _aware(proposal.expires_at)
    if expires_at is not None and expires_at <= utc_now():
        raise ConflictError("Action proposal has expired")


async def _proposal_event(
    session: AsyncSession,
    context: RequestContext,
    proposal: ActionProposal,
    event_type: str,
    reason: str | None,
) -> None:
    await record_audit(
        session,
        context,
        event_type,
        "action_proposal",
        proposal.id,
        reason=reason,
        details={"status": proposal.status, "version": proposal.version},
    )
    await record_outbox_event(
        session,
        context,
        event_type,
        "action_proposal",
        proposal.id,
        {"status": proposal.status, "version": proposal.version},
    )


async def expire_proposals(
    session: AsyncSession,
    context: RequestContext,
) -> list[ActionProposal]:
    _require_permission(context, Permission.ACTIONS_RECOVER)
    now = utc_now()
    result = await session.scalars(
        select(ActionProposal).where(
            ActionProposal.tenant_id == context.tenant_id,
            ActionProposal.status.in_({"proposed", "edited", "approved"}),
            ActionProposal.expires_at <= now,
        )
    )
    proposals = list(result)
    for proposal in proposals:
        proposal.status = "expired"
        proposal.version += 1
        proposal.updated_at = now
        await _proposal_event(session, context, proposal, "action.proposal.expired", "expiration")
    await session.commit()
    for proposal in proposals:
        await session.refresh(proposal)
    return proposals


async def dry_run_action(
    context: RequestContext,
    action_type: str,
    payload: dict[str, object],
) -> ActionDryRunResponse:
    _require_permission(context, Permission.ACTIONS_PROPOSE)
    definition = get_action_definition(action_type)
    _require_permission(context, definition.required_permission)
    normalized = definition.validate(payload)
    normalized_payload = normalized.model_dump(mode="json", exclude_unset=True)
    return ActionDryRunResponse(
        action_type=definition.action_type,
        action_version=definition.version,
        required_permission=definition.required_permission.value,
        risk_level=definition.risk_level,
        requires_approval=definition.requires_approval,
        valid=True,
        normalized_payload=normalized_payload,
        affected_resources=_resource_refs(definition.action_type, normalized_payload),
        intended_changes=normalized_payload,
        expected_side_effects=list(definition.expected_side_effects),
    )


async def execute_proposal(
    session: AsyncSession,
    context: RequestContext,
    proposal_id: str,
    expected_version: int | None,
) -> ActionExecution:
    _require_permission(context, Permission.ACTIONS_EXECUTE)
    proposal = await get_proposal(session, context, proposal_id)
    _check_version(proposal, expected_version)
    _ensure_not_expired(proposal)
    if proposal.status != "approved":
        raise InvalidTransitionError(f"Only approved proposals can execute: {proposal.status}")
    definition = get_action_definition(proposal.action_type)
    _require_permission(context, definition.required_permission)
    definition.validate(proposal.payload)
    existing = await session.scalar(
        select(ActionExecution).where(
            ActionExecution.tenant_id == context.tenant_id,
            ActionExecution.action_proposal_id == proposal.id,
        )
    )
    if existing is not None:
        if existing.status == "succeeded":
            return existing
        raise ConflictError(f"Action execution already exists in state {existing.status}")
    execution = ActionExecution(
        tenant_id=context.tenant_id,
        action_proposal_id=proposal.id,
        idempotency_key=f"action:{proposal.id}",
        action_type=proposal.action_type,
        request_hash=proposal.request_hash,
        status="executing",
        attempts=1,
        started_at=utc_now(),
    )
    proposal.status = "executing"
    proposal.version += 1
    proposal.updated_at = utc_now()
    session.add(execution)
    await _proposal_event(session, context, proposal, "action.execution.started", None)
    await session.commit()
    await session.refresh(execution)
    return await _run_execution(session, context, proposal.id, execution.id)


async def retry_execution(
    session: AsyncSession,
    context: RequestContext,
    execution_id: str,
    payload: ActionRecoveryRequest,
) -> ActionExecution:
    _require_permission(context, Permission.ACTIONS_RECOVER)
    execution = await get_execution(session, context, execution_id)
    if execution.status == "uncertain":
        raise ConflictError("Reconcile an uncertain external outcome before retrying")
    if execution.status not in {"failed", "recoverable"}:
        raise ConflictError(f"Only failed or recoverable executions can retry: {execution.status}")
    proposal = await get_proposal(session, context, execution.action_proposal_id)
    _ensure_not_expired(proposal)
    definition = get_action_definition(proposal.action_type)
    _require_permission(context, definition.required_permission)
    if execution.attempts >= definition.max_attempts:
        raise ConflictError("Action execution has exhausted its retry limit")
    proposal.status = "approved"
    proposal.version += 1
    proposal.updated_at = utc_now()
    execution.status = "executing"
    execution.attempts += 1
    execution.operator_note = payload.operator_note
    execution.error_code = None
    execution.error_detail = None
    execution.uncertain_outcome = False
    execution.started_at = utc_now()
    await _proposal_event(
        session,
        context,
        proposal,
        "action.execution.retried",
        payload.operator_note,
    )
    await session.commit()
    return await _run_execution(session, context, proposal.id, execution.id)


async def reconcile_execution(
    session: AsyncSession,
    context: RequestContext,
    execution_id: str,
    payload: ActionRecoveryRequest,
) -> ActionExecution:
    _require_permission(context, Permission.ACTIONS_RECOVER)
    execution = await get_execution(session, context, execution_id)
    if execution.status != "uncertain":
        raise ConflictError("Only uncertain executions can be reconciled")
    write = await session.scalar(
        select(ExternalWrite).where(
            ExternalWrite.idempotency_key == execution.idempotency_key,
        )
    )
    if write is None:
        raise ConflictError("External outcome is not available for reconciliation")
    if write.status != "succeeded":
        execution.operator_note = payload.operator_note
        await session.commit()
        raise ConflictError("External outcome is still unresolved")
    proposal = await get_proposal(session, context, execution.action_proposal_id)
    execution.status = "succeeded"
    execution.result = {
        "external_write_id": write.id,
        "response_metadata": write.response_metadata,
        "reconciled": True,
    }
    execution.provider_request_id = write.provider_request_id
    execution.uncertain_outcome = False
    execution.operator_note = payload.operator_note
    execution.completed_at = utc_now()
    proposal.status = "succeeded"
    proposal.version += 1
    proposal.updated_at = utc_now()
    await record_audit(
        session,
        context,
        "action.execution.reconciled",
        "action_execution",
        execution.id,
        details={"proposal_id": proposal.id, "external_write_id": write.id},
    )
    await session.commit()
    await session.refresh(execution)
    return execution


async def _run_execution(
    session: AsyncSession,
    context: RequestContext,
    proposal_id: str,
    execution_id: str,
) -> ActionExecution:
    proposal = await get_proposal(session, context, proposal_id)
    execution = await get_execution(session, context, execution_id)
    definition = get_action_definition(proposal.action_type)
    try:
        result = await _execute_effect(session, context, definition, proposal.payload, execution)
        execution.status = "succeeded"
        execution.result = result
        execution.completed_at = utc_now()
        proposal.status = "succeeded"
        proposal.version += 1
        proposal.updated_at = utc_now()
        proposal.last_error_code = None
        proposal.last_error_detail = None
        await record_audit(
            session,
            context,
            "action.execution.succeeded",
            "action_execution",
            execution.id,
            details={"proposal_id": proposal.id, "action_type": proposal.action_type},
        )
        await record_outbox_event(
            session,
            context,
            "action.execution.succeeded",
            "action_execution",
            execution.id,
            {"proposal_id": proposal.id, "action_type": proposal.action_type},
        )
    except ConnectorProviderError as error:
        uncertain = error.code in {"uncertain", "timeout", "provider_timeout"}
        execution.status = "uncertain" if uncertain else "recoverable"
        execution.uncertain_outcome = uncertain
        execution.error_code = error.code
        execution.error_detail = str(error)[:500]
        proposal.status = "recoverable" if uncertain else "failed"
        proposal.last_error_code = error.code
        proposal.last_error_detail = str(error)[:500]
        proposal.version += 1
        proposal.updated_at = utc_now()
        await record_audit(
            session,
            context,
            "action.execution.recoverable" if uncertain else "action.execution.failed",
            "action_execution",
            execution.id,
            outcome="failed",
            reason=error.code,
            details={"proposal_id": proposal.id, "uncertain": uncertain},
        )
    except (DomainError, ValueError) as error:
        execution.status = "failed"
        execution.error_code = _error_code(error)
        execution.error_detail = str(error)[:500]
        proposal.status = "failed"
        proposal.last_error_code = execution.error_code
        proposal.last_error_detail = execution.error_detail
        proposal.version += 1
        proposal.updated_at = utc_now()
        await record_audit(
            session,
            context,
            "action.execution.failed",
            "action_execution",
            execution.id,
            outcome="failed",
            reason=execution.error_code,
            details={"proposal_id": proposal.id},
        )
    execution.updated_at = utc_now()
    await session.commit()
    await session.refresh(execution)
    return execution


def _error_code(error: Exception) -> str:
    if isinstance(error, VersionConflictError):
        return "record_version_conflict"
    if isinstance(error, InvalidRequestError):
        return "invalid_request"
    if isinstance(error, NotFoundError):
        return "not_found"
    if isinstance(error, InvalidTransitionError):
        return "invalid_transition"
    return "action_failed"


async def _execute_effect(
    session: AsyncSession,
    context: RequestContext,
    definition: ActionDefinition,
    raw_payload: dict[str, object],
    execution: ActionExecution,
) -> dict[str, object]:
    payload = definition.validate(raw_payload)
    if definition.executor_key == "task.create":
        return await _create_task(session, context, payload)
    if definition.executor_key == "contact.update":
        return await _update_contact(session, context, payload)
    if definition.executor_key == "contact.assign_owner":
        return await _assign_contact_owner(session, context, payload)
    if definition.executor_key == "activity.create":
        return await _create_activity(session, context, payload)
    if definition.executor_key == "approval.request":
        return await _create_approval_work_item(session, context, payload)
    if definition.executor_key == "integration.activity.create":
        return await _create_external_activity(session, context, payload, execution)
    raise InvalidRequestError(f"No executor registered for {definition.action_type}")


async def _validate_relationships(
    session: AsyncSession,
    context: RequestContext,
    *,
    contact_id: str | None = None,
    company_id: str | None = None,
    opportunity_id: str | None = None,
) -> None:
    for model, identifier, label in (
        (Contact, contact_id, "Contact"),
        (Opportunity, opportunity_id, "Opportunity"),
    ):
        if identifier is not None:
            found = await session.scalar(
                select(model).where(model.id == identifier, model.tenant_id == context.tenant_id)
            )
            if found is None:
                raise NotFoundError(f"{label} not found")
    if company_id is not None:
        from ..models import Company

        found = await session.scalar(
            select(Company).where(Company.id == company_id, Company.tenant_id == context.tenant_id)
        )
        if found is None:
            raise NotFoundError("Company not found")


async def _create_task(
    session: AsyncSession,
    context: RequestContext,
    payload: BaseModel,
) -> dict[str, object]:
    task_payload = TaskCreate.model_validate(payload.model_dump(exclude_unset=True))
    if task_payload.status not in {"open", "in_progress", "completed", "cancelled"}:
        raise InvalidRequestError("Invalid task status")
    await _validate_relationships(
        session,
        context,
        contact_id=task_payload.contact_id,
        opportunity_id=task_payload.opportunity_id,
    )
    values = task_payload.model_dump()
    task = Task(
        tenant_id=context.tenant_id,
        completed_at=utc_now() if values["status"] == "completed" else None,
        **values,
    )
    session.add(task)
    await session.flush()
    await record_audit(
        session,
        context,
        "task.created",
        "task",
        task.id,
        details={"version": task.version, "via": "action_execution"},
    )
    await record_outbox_event(
        session,
        context,
        "task.created",
        "task",
        task.id,
        {"version": task.version, "via": "action_execution"},
    )
    return {"entity_type": "task", "entity_id": task.id, "version": task.version}


async def _get_contact(
    session: AsyncSession,
    context: RequestContext,
    contact_id: str,
) -> Contact:
    contact = await session.scalar(
        select(Contact).where(Contact.id == contact_id, Contact.tenant_id == context.tenant_id)
    )
    if contact is None:
        raise NotFoundError("Contact not found")
    return contact


async def _apply_contact_update(
    session: AsyncSession,
    context: RequestContext,
    contact: Contact,
    changes: ContactUpdate,
    expected_version: int,
) -> dict[str, object]:
    if contact.version != expected_version:
        raise VersionConflictError("record_version_conflict")
    values = changes.model_dump(exclude_unset=True)
    archived = values.pop("archived", None)
    if not values and archived is None:
        raise InvalidRequestError("At least one contact field is required")
    if "company_id" in values:
        await _validate_relationships(session, context, company_id=values["company_id"])
    if "status" in values:
        allowed = {
            "lead": {"qualified", "lost"},
            "qualified": {"customer", "lost"},
            "customer": {"lost"},
            "lost": set(),
        }
        if values["status"] != contact.status and values["status"] not in allowed.get(
            contact.status, set()
        ):
            raise InvalidTransitionError(
                f"Cannot transition contact from {contact.status} to {values['status']}"
            )
    if archived is not None:
        values["archived_at"] = utc_now() if archived else None
    old_state = {key: _json_safe(getattr(contact, key)) for key in values if hasattr(contact, key)}
    update_values = {**values, "version": expected_version + 1, "updated_at": utc_now()}
    result = cast(
        CursorResult[Any],
        await session.execute(
            update(Contact)
            .where(
                Contact.id == contact.id,
                Contact.tenant_id == context.tenant_id,
                Contact.version == expected_version,
            )
            .values(**update_values)
        ),
    )
    if result.rowcount != 1:
        raise VersionConflictError("record_version_conflict")
    await record_audit(
        session,
        context,
        "contact.updated",
        "contact",
        contact.id,
        details={"old": old_state, "new": _json_safe(update_values), "via": "action_execution"},
    )
    await record_outbox_event(
        session,
        context,
        "contact.updated",
        "contact",
        contact.id,
        {"new": _json_safe(update_values), "via": "action_execution"},
    )
    return {"entity_type": "contact", "entity_id": contact.id, "version": expected_version + 1}


async def _update_contact(
    session: AsyncSession,
    context: RequestContext,
    payload: BaseModel,
) -> dict[str, object]:
    action = ContactUpdateAction.model_validate(payload.model_dump(exclude_unset=True))
    contact = await _get_contact(session, context, action.contact_id)
    return await _apply_contact_update(
        session,
        context,
        contact,
        action.changes,
        action.expected_version,
    )


async def _assign_contact_owner(
    session: AsyncSession,
    context: RequestContext,
    payload: BaseModel,
) -> dict[str, object]:
    action = ContactAssignOwnerAction.model_validate(payload.model_dump())
    contact = await _get_contact(session, context, action.contact_id)
    return await _apply_contact_update(
        session,
        context,
        contact,
        ContactUpdate(owner_id=action.owner_id),
        action.expected_version,
    )


async def _create_activity(
    session: AsyncSession,
    context: RequestContext,
    payload: BaseModel,
) -> dict[str, object]:
    activity_payload = ActivityCreate.model_validate(payload.model_dump(exclude_unset=True))
    await _validate_relationships(
        session,
        context,
        contact_id=activity_payload.contact_id,
        company_id=activity_payload.company_id,
        opportunity_id=activity_payload.opportunity_id,
    )
    values = activity_payload.model_dump()
    values["event_at"] = values["event_at"] or utc_now()
    activity = Activity(tenant_id=context.tenant_id, actor_id=context.actor_id, **values)
    session.add(activity)
    await session.flush()
    await record_audit(
        session,
        context,
        "activity.created",
        "activity",
        activity.id,
        details={"via": "action_execution"},
    )
    await record_outbox_event(
        session,
        context,
        "activity.created",
        "activity",
        activity.id,
        {"via": "action_execution"},
    )
    return {"entity_type": "activity", "entity_id": activity.id}


async def _create_approval_work_item(
    session: AsyncSession,
    context: RequestContext,
    payload: BaseModel,
) -> dict[str, object]:
    action = ApprovalRequestAction.model_validate(payload.model_dump())
    work_item = WorkItem(
        tenant_id=context.tenant_id,
        item_type="approval",
        title=action.title,
        description=action.description,
        status="open",
        priority=50,
        owner_id=context.actor_id,
        assignee_id=action.assignee_id,
        due_at=action.due_at,
        source=action.source,
        created_by=context.actor_id,
    )
    session.add(work_item)
    await session.flush()
    await record_audit(
        session,
        context,
        "work_item.created",
        "work_item",
        work_item.id,
        details={"item_type": "approval", "via": "action_execution"},
    )
    await record_outbox_event(
        session,
        context,
        "work_item.created",
        "work_item",
        work_item.id,
        {"item_type": "approval", "via": "action_execution"},
    )
    return {"entity_type": "work_item", "entity_id": work_item.id, "item_type": "approval"}


async def _create_external_activity(
    session: AsyncSession,
    context: RequestContext,
    payload: BaseModel,
    execution: ActionExecution,
) -> dict[str, object]:
    action = ExternalActivityAction.model_validate(payload.model_dump())
    connection = await session.scalar(
        select(IntegrationConnection).where(
            IntegrationConnection.id == action.connection_id,
            IntegrationConnection.tenant_id == context.tenant_id,
        )
    )
    if connection is None:
        raise NotFoundError("Integration connection not found")
    connection_is_writable(connection)
    write = await session.scalar(
        select(ExternalWrite).where(
            ExternalWrite.connection_id == connection.id,
            ExternalWrite.idempotency_key == execution.idempotency_key,
        )
    )
    if write is None:
        write = ExternalWrite(
            connection_id=connection.id,
            idempotency_key=execution.idempotency_key,
            operation="activity.create",
            request_hash=_hash_payload("activity.create", action.model_dump(mode="json")),
            status="pending",
            attempts=execution.attempts,
        )
        session.add(write)
        await session.flush()
    elif write.status == "succeeded":
        return {
            "external_write_id": write.id,
            "provider_request_id": write.provider_request_id,
            "response_metadata": write.response_metadata,
            "replayed": True,
        }
    connector = get_connector(connection.provider_key)
    try:
        result = await connector.write(
            connection,
            "activity.create",
            {"subject": action.subject, "body": action.body},
            execution.idempotency_key,
        )
    except ConnectorProviderError as error:
        write.status = "failed"
        write.last_error = error.code
        raise
    write.status = "succeeded"
    write.provider_request_id = result.provider_request_id
    write.response_metadata = result.response_metadata
    write.updated_at = utc_now()
    execution.provider_request_id = result.provider_request_id
    return {
        "external_write_id": write.id,
        "provider_request_id": result.provider_request_id,
        "response_metadata": result.response_metadata,
    }
