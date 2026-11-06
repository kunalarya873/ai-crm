from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..actions import (
    ACTION_REGISTRY,
    approve_proposal,
    create_proposal,
    dry_run_action,
    edit_proposal,
    execute_proposal,
    expire_proposals,
    get_execution,
    get_proposal,
    list_executions,
    list_proposals,
    reconcile_execution,
    reject_proposal,
    retry_execution,
    revoke_proposal,
)
from ..api.deps import RequestContext, require_permission
from ..db import get_session
from ..permissions import Permission
from ..schemas import (
    ActionDecision,
    ActionDryRunResponse,
    ActionExecutionRead,
    ActionProposalCreate,
    ActionProposalEdit,
    ActionProposalRead,
    ActionRecoveryRequest,
    ActionRegistryRead,
)
from .routes import parse_if_match, set_etag

router = APIRouter()
SessionDependency = Annotated[AsyncSession, Depends(get_session)]
ReadContext = Annotated[
    RequestContext,
    Depends(require_permission(Permission.ACTIONS_READ)),
]
ProposeContext = Annotated[
    RequestContext,
    Depends(require_permission(Permission.ACTIONS_PROPOSE)),
]
ApproveContext = Annotated[
    RequestContext,
    Depends(require_permission(Permission.ACTIONS_APPROVE)),
]
ExecuteContext = Annotated[
    RequestContext,
    Depends(require_permission(Permission.ACTIONS_EXECUTE)),
]
RecoverContext = Annotated[
    RequestContext,
    Depends(require_permission(Permission.ACTIONS_RECOVER)),
]


@router.get("/actions/registry", response_model=list[ActionRegistryRead], tags=["actions"])
async def action_registry_endpoint(context: ReadContext) -> list[ActionRegistryRead]:
    _ = context
    return [
        ActionRegistryRead(
            action_type=definition.action_type,
            version=definition.version,
            required_permission=definition.required_permission.value,
            risk_level=definition.risk_level,
            requires_approval=definition.requires_approval,
            timeout_seconds=definition.timeout_seconds,
            max_attempts=definition.max_attempts,
            affected_resource_types=list(definition.affected_resource_types),
        )
        for definition in ACTION_REGISTRY.values()
    ]


@router.post(
    "/actions/dry-run",
    response_model=ActionDryRunResponse,
    tags=["actions"],
)
async def dry_run_action_endpoint(
    action_type: str,
    payload: dict[str, object],
    context: ProposeContext,
) -> ActionDryRunResponse:
    return await dry_run_action(context, action_type, payload)


@router.post(
    "/actions/proposals",
    response_model=ActionProposalRead,
    status_code=status.HTTP_201_CREATED,
    tags=["actions"],
)
async def create_action_proposal_endpoint(
    payload: ActionProposalCreate,
    response: Response,
    session: SessionDependency,
    context: ProposeContext,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ActionProposalRead:
    proposal = await create_proposal(session, context, payload, idempotency_key or "")
    set_etag(response, proposal.version)
    return ActionProposalRead.model_validate(proposal)


@router.get("/actions/proposals", response_model=list[ActionProposalRead], tags=["actions"])
async def list_action_proposals_endpoint(
    session: SessionDependency,
    context: ReadContext,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    action_type: str | None = None,
    proposal_status: str | None = Query(default=None, alias="status"),
) -> list[ActionProposalRead]:
    proposals = await list_proposals(
        session,
        context,
        limit=limit,
        offset=offset,
        action_type=action_type,
        proposal_status=proposal_status,
    )
    return [ActionProposalRead.model_validate(proposal) for proposal in proposals]


@router.get(
    "/actions/proposals/{proposal_id}",
    response_model=ActionProposalRead,
    tags=["actions"],
)
async def get_action_proposal_endpoint(
    proposal_id: str,
    response: Response,
    session: SessionDependency,
    context: ReadContext,
) -> ActionProposalRead:
    proposal = await get_proposal(session, context, proposal_id)
    set_etag(response, proposal.version)
    return ActionProposalRead.model_validate(proposal)


@router.post(
    "/actions/proposals/{proposal_id}/approve",
    response_model=ActionProposalRead,
    tags=["actions"],
)
async def approve_action_proposal_endpoint(
    proposal_id: str,
    payload: ActionDecision,
    response: Response,
    session: SessionDependency,
    context: ApproveContext,
    if_match: Annotated[str | None, Header()] = None,
) -> ActionProposalRead:
    proposal = await approve_proposal(
        session,
        context,
        proposal_id,
        parse_if_match(if_match),
        payload,
    )
    set_etag(response, proposal.version)
    return ActionProposalRead.model_validate(proposal)


@router.post(
    "/actions/proposals/{proposal_id}/reject",
    response_model=ActionProposalRead,
    tags=["actions"],
)
async def reject_action_proposal_endpoint(
    proposal_id: str,
    payload: ActionDecision,
    response: Response,
    session: SessionDependency,
    context: ApproveContext,
    if_match: Annotated[str | None, Header()] = None,
) -> ActionProposalRead:
    proposal = await reject_proposal(
        session,
        context,
        proposal_id,
        parse_if_match(if_match),
        payload,
    )
    set_etag(response, proposal.version)
    return ActionProposalRead.model_validate(proposal)


@router.patch(
    "/actions/proposals/{proposal_id}",
    response_model=ActionProposalRead,
    tags=["actions"],
)
async def edit_action_proposal_endpoint(
    proposal_id: str,
    payload: ActionProposalEdit,
    response: Response,
    session: SessionDependency,
    context: ProposeContext,
    if_match: Annotated[str | None, Header()] = None,
) -> ActionProposalRead:
    proposal = await edit_proposal(
        session,
        context,
        proposal_id,
        parse_if_match(if_match),
        payload,
    )
    set_etag(response, proposal.version)
    return ActionProposalRead.model_validate(proposal)


@router.post(
    "/actions/proposals/{proposal_id}/revoke",
    response_model=ActionProposalRead,
    tags=["actions"],
)
async def revoke_action_proposal_endpoint(
    proposal_id: str,
    payload: ActionDecision,
    response: Response,
    session: SessionDependency,
    context: ProposeContext,
    if_match: Annotated[str | None, Header()] = None,
) -> ActionProposalRead:
    proposal = await revoke_proposal(
        session,
        context,
        proposal_id,
        parse_if_match(if_match),
        payload,
    )
    set_etag(response, proposal.version)
    return ActionProposalRead.model_validate(proposal)


@router.post(
    "/actions/proposals/{proposal_id}/execute",
    response_model=ActionExecutionRead,
    tags=["actions"],
)
async def execute_action_proposal_endpoint(
    proposal_id: str,
    session: SessionDependency,
    context: ExecuteContext,
    if_match: Annotated[str | None, Header()] = None,
) -> ActionExecutionRead:
    execution = await execute_proposal(
        session,
        context,
        proposal_id,
        parse_if_match(if_match),
    )
    return ActionExecutionRead.model_validate(execution)


@router.post(
    "/actions/proposals/expire",
    response_model=list[ActionProposalRead],
    tags=["actions"],
)
async def expire_action_proposals_endpoint(
    session: SessionDependency,
    context: RecoverContext,
) -> list[ActionProposalRead]:
    proposals = await expire_proposals(session, context)
    return [ActionProposalRead.model_validate(proposal) for proposal in proposals]


@router.get("/actions/executions", response_model=list[ActionExecutionRead], tags=["actions"])
async def list_action_executions_endpoint(
    session: SessionDependency,
    context: ReadContext,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    execution_status: str | None = Query(default=None, alias="status"),
) -> list[ActionExecutionRead]:
    executions = await list_executions(
        session,
        context,
        limit=limit,
        offset=offset,
        execution_status=execution_status,
    )
    return [ActionExecutionRead.model_validate(execution) for execution in executions]


@router.get(
    "/actions/executions/{execution_id}",
    response_model=ActionExecutionRead,
    tags=["actions"],
)
async def get_action_execution_endpoint(
    execution_id: str,
    session: SessionDependency,
    context: ReadContext,
) -> ActionExecutionRead:
    return ActionExecutionRead.model_validate(await get_execution(session, context, execution_id))


@router.post(
    "/actions/executions/{execution_id}/retry",
    response_model=ActionExecutionRead,
    tags=["actions"],
)
async def retry_action_execution_endpoint(
    execution_id: str,
    payload: ActionRecoveryRequest,
    session: SessionDependency,
    context: RecoverContext,
) -> ActionExecutionRead:
    execution = await retry_execution(session, context, execution_id, payload)
    return ActionExecutionRead.model_validate(execution)


@router.post(
    "/actions/executions/{execution_id}/reconcile",
    response_model=ActionExecutionRead,
    tags=["actions"],
)
async def reconcile_action_execution_endpoint(
    execution_id: str,
    payload: ActionRecoveryRequest,
    session: SessionDependency,
    context: RecoverContext,
) -> ActionExecutionRead:
    execution = await reconcile_execution(session, context, execution_id, payload)
    return ActionExecutionRead.model_validate(execution)
