from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import RequestContext
from ...knowledge.retrieval import assemble_context
from ...models import Agent, AgentRun
from ...schemas import AgentStepCreate, KnowledgeContextRequest
from .base import agent_context
from .outcome import _denial, _Outcome, _parse

__all__ = [
    "_do_retrieve",
]


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
