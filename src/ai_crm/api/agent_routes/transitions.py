from typing import Annotated

from fastapi import Header, Response

from ...agents import (
    list_messages,
    transition_run,
)
from ...schemas import (
    AgentMessageRead,
    AgentRunRead,
)
from ..routes import parse_if_match, set_etag
from .base import ReadContext, RunContext, SessionDependency, router

__all__ = [
    "_transition_route", "list_messages_endpoint",
]


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
