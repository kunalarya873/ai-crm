from typing import Annotated

from fastapi import Header, Query

from ...actions import (
    execute_proposal,
    expire_proposals,
    get_execution,
    list_executions,
    reconcile_execution,
    retry_execution,
)
from ...schemas import (
    ActionExecutionRead,
    ActionProposalRead,
    ActionRecoveryRequest,
)
from ..routes import parse_if_match
from .base import ExecuteContext, ReadContext, RecoverContext, SessionDependency, router

__all__ = [
    "execute_action_proposal_endpoint", "expire_action_proposals_endpoint",
    "get_action_execution_endpoint", "list_action_executions_endpoint",
    "reconcile_action_execution_endpoint", "retry_action_execution_endpoint",
]


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
