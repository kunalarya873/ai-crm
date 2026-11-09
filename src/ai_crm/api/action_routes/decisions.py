from typing import Annotated

from fastapi import Header, Response

from ...actions import (
    approve_proposal,
    edit_proposal,
    reject_proposal,
    revoke_proposal,
)
from ...schemas import (
    ActionDecision,
    ActionProposalEdit,
    ActionProposalRead,
)
from ..routes import parse_if_match, set_etag
from .base import ApproveContext, ProposeContext, SessionDependency, router

__all__ = [
    "approve_action_proposal_endpoint", "edit_action_proposal_endpoint",
    "reject_action_proposal_endpoint", "revoke_action_proposal_endpoint",
]


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
