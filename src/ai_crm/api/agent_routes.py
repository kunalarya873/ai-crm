from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..agents import (
    get_agent,
    get_run,
    list_agents,
    list_messages,
    list_runs,
    list_steps,
    register_agent,
    start_run,
    submit_step,
    transition_run,
    update_agent,
)
from ..api.deps import RequestContext, require_permission
from ..db import get_session
from ..permissions import Permission
from ..schemas import (
    AgentCreate,
    AgentMessageRead,
    AgentRead,
    AgentRunCreate,
    AgentRunDetail,
    AgentRunRead,
    AgentStepCreate,
    AgentStepRead,
    AgentStepResult,
    AgentUpdate,
)
from .routes import parse_if_match, set_etag, trim_page

router = APIRouter()
SessionDependency = Annotated[AsyncSession, Depends(get_session)]
ReadContext = Annotated[RequestContext, Depends(require_permission(Permission.AGENTS_READ))]
RunContext = Annotated[RequestContext, Depends(require_permission(Permission.AGENTS_RUN))]
ManageContext = Annotated[RequestContext, Depends(require_permission(Permission.AGENTS_MANAGE))]


@router.post(
    "/agents", response_model=AgentRead, status_code=status.HTTP_201_CREATED, tags=["agents"]
)
async def register_agent_endpoint(
    payload: AgentCreate, response: Response, session: SessionDependency, context: ManageContext
) -> AgentRead:
    agent = await register_agent(session, context, payload)
    set_etag(response, agent.version)
    return AgentRead.model_validate(agent)


@router.get("/agents", response_model=list[AgentRead], tags=["agents"])
async def list_agents_endpoint(
    response: Response,
    session: SessionDependency,
    context: ReadContext,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    cursor: str | None = None,
    agent_status: Annotated[str | None, Query(alias="status")] = None,
) -> list[AgentRead]:
    agents = await list_agents(
        session, context, limit=limit + 1, offset=offset, cursor=cursor, status=agent_status
    )
    return [AgentRead.model_validate(agent) for agent in trim_page(response, agents, limit)]


@router.get("/agents/{agent_id}", response_model=AgentRead, tags=["agents"])
async def get_agent_endpoint(
    agent_id: str, response: Response, session: SessionDependency, context: ReadContext
) -> AgentRead:
    agent = await get_agent(session, context, agent_id)
    set_etag(response, agent.version)
    return AgentRead.model_validate(agent)


@router.patch("/agents/{agent_id}", response_model=AgentRead, tags=["agents"])
async def update_agent_endpoint(
    agent_id: str,
    payload: AgentUpdate,
    response: Response,
    session: SessionDependency,
    context: ManageContext,
    if_match: Annotated[str | None, Header()] = None,
) -> AgentRead:
    agent = await update_agent(session, context, agent_id, payload, parse_if_match(if_match))
    set_etag(response, agent.version)
    return AgentRead.model_validate(agent)


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


def _transition_route(action: str) -> None:
    @router.post(
        f"/agent-runs/{{run_id}}/{action}", response_model=AgentRunRead, tags=["agents"]
    )
    async def endpoint(
        run_id: str,
        response: Response,
        session: SessionDependency,
        context: RunContext,
        if_match: Annotated[str | None, Header()] = None,
    ) -> AgentRunRead:
        run = await transition_run(session, context, run_id, action, parse_if_match(if_match))
        set_etag(response, run.version)
        return AgentRunRead.model_validate(run)

    endpoint.__name__ = f"{action}_run_endpoint"


for _action in ("pause", "resume", "cancel"):
    _transition_route(_action)


@router.get(
    "/agent-runs/{run_id}/messages", response_model=list[AgentMessageRead], tags=["agents"]
)
async def list_messages_endpoint(
    run_id: str, session: SessionDependency, context: ReadContext
) -> list[AgentMessageRead]:
    messages = await list_messages(session, context, run_id)
    return [AgentMessageRead.model_validate(message) for message in messages]
