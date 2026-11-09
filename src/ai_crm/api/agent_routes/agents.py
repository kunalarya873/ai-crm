from typing import Annotated

from fastapi import Header, Query, Response, status

from ...agents import (
    get_agent,
    list_agents,
    register_agent,
    update_agent,
)
from ...schemas import (
    AgentCreate,
    AgentRead,
    AgentUpdate,
)
from ..routes import parse_if_match, set_etag, trim_page
from .base import ManageContext, ReadContext, SessionDependency, router

__all__ = [
    "get_agent_endpoint", "list_agents_endpoint", "register_agent_endpoint",
    "update_agent_endpoint",
]


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
