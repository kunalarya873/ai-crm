from typing import Annotated

from fastapi import Header, Query, Response, status

from ...actions import (
    ACTION_REGISTRY,
    create_proposal,
    dry_run_action,
    get_proposal,
    list_proposals,
)
from ...schemas import (
    ActionDryRunResponse,
    ActionProposalCreate,
    ActionProposalRead,
    ActionRegistryRead,
)
from ..routes import set_etag
from .base import ProposeContext, ReadContext, SessionDependency, router

__all__ = [
    "action_registry_endpoint", "create_action_proposal_endpoint", "dry_run_action_endpoint",
    "get_action_proposal_endpoint", "list_action_proposals_endpoint",
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
