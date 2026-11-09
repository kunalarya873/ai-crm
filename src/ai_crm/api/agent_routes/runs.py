from typing import Annotated

from fastapi import Header, Query, Response, status

from ...agents import (
    get_run,
    list_runs,
    list_steps,
    start_run,
    submit_step,
)
from ...schemas import (
    AgentRunCreate,
    AgentRunDetail,
    AgentRunRead,
    AgentStepCreate,
    AgentStepRead,
    AgentStepResult,
)
from ..routes import set_etag, trim_page
from .base import ReadContext, RunContext, SessionDependency, router

__all__ = [
    "get_run_endpoint", "list_runs_endpoint", "start_run_endpoint", "submit_step_endpoint",
]


@router.post(
    "/agent-runs",
    response_model=AgentRunRead,
    status_code=status.HTTP_201_CREATED,
    tags=["agents"],
)
async def start_run_endpoint(
    payload: AgentRunCreate,
    response: Response,
    session: SessionDependency,
    context: RunContext,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> AgentRunRead:
    run = await start_run(session, context, payload, idempotency_key or "")
    set_etag(response, run.version)
    return AgentRunRead.model_validate(run)


@router.get("/agent-runs", response_model=list[AgentRunRead], tags=["agents"])
async def list_runs_endpoint(
    response: Response,
    session: SessionDependency,
    context: ReadContext,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    cursor: str | None = None,
    run_status: Annotated[str | None, Query(alias="status")] = None,
    agent_id: str | None = None,
    root_run_id: str | None = None,
) -> list[AgentRunRead]:
    runs = await list_runs(
        session,
        context,
        limit=limit + 1,
        offset=offset,
        cursor=cursor,
        status=run_status,
        agent_id=agent_id,
        root_run_id=root_run_id,
    )
    return [AgentRunRead.model_validate(run) for run in trim_page(response, runs, limit)]


@router.get("/agent-runs/{run_id}", response_model=AgentRunDetail, tags=["agents"])
async def get_run_endpoint(
    run_id: str, response: Response, session: SessionDependency, context: ReadContext
) -> AgentRunDetail:
    run = await get_run(session, context, run_id)
    steps = await list_steps(session, context, run_id)
    set_etag(response, run.version)
    return AgentRunDetail(
        **AgentRunRead.model_validate(run).model_dump(),
        steps=[AgentStepRead.model_validate(step) for step in steps],
    )


@router.post(
    "/agent-runs/{run_id}/steps",
    response_model=AgentStepResult,
    status_code=status.HTTP_201_CREATED,
    tags=["agents"],
)
async def submit_step_endpoint(
    run_id: str,
    payload: AgentStepCreate,
    response: Response,
    session: SessionDependency,
    context: RunContext,
) -> AgentStepResult:
    result = await submit_step(session, context, run_id, payload)
    set_etag(response, result.run.version)
    return result
