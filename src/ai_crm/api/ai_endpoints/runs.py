from fastapi import Query, status

from ...ai.use_cases import feedback_read, run_read
from ...schemas import (
    AIFeedbackCreate,
    AIFeedbackRead,
    AIProviderHealthRead,
    AIRunRead,
)
from .base import AIFeedbackContext, AIReadContext, SessionDependency, current_service, router

__all__ = [
    "get_ai_run_endpoint", "list_ai_runs_endpoint", "provider_health_endpoint",
    "record_ai_feedback_endpoint",
]


@router.get("/ai/providers/health", response_model=AIProviderHealthRead, tags=["ai"])
async def provider_health_endpoint(context: AIReadContext) -> AIProviderHealthRead:
    _ = context
    return await current_service().provider_health()


@router.get("/ai/runs", response_model=list[AIRunRead], tags=["ai"])
async def list_ai_runs_endpoint(
    session: SessionDependency,
    context: AIReadContext,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    use_case: str | None = None,
    run_status: str | None = Query(default=None, alias="status"),
) -> list[AIRunRead]:
    runs = await current_service().list_runs(
        session,
        context,
        limit=limit,
        offset=offset,
        use_case=use_case,
        run_status=run_status,
    )
    return [run_read(run) for run in runs]


@router.get("/ai/runs/{run_id}", response_model=AIRunRead, tags=["ai"])
async def get_ai_run_endpoint(
    run_id: str,
    session: SessionDependency,
    context: AIReadContext,
) -> AIRunRead:
    return run_read(await current_service().get_run(session, context, run_id))


@router.post(
    "/ai/runs/{run_id}/feedback",
    response_model=AIFeedbackRead,
    status_code=status.HTTP_201_CREATED,
    tags=["ai"],
)
async def record_ai_feedback_endpoint(
    run_id: str,
    payload: AIFeedbackCreate,
    session: SessionDependency,
    context: AIFeedbackContext,
) -> AIFeedbackRead:
    feedback = await current_service().record_feedback(session, context, run_id, payload)
    return feedback_read(feedback)
