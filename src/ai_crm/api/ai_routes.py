from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..ai.use_cases import AIUseCaseService, feedback_read, run_read
from ..api.deps import RequestContext, require_permission
from ..db import get_session
from ..permissions import Permission
from ..schemas import (
    AICommunicationDraftRequest,
    AICommunicationDraftResponse,
    AICustomerSummaryResponse,
    AIExtractionRequest,
    AIFeedbackCreate,
    AIFeedbackRead,
    AIFieldExtractionResponse,
    AINextStepRequest,
    AINextStepResponse,
    AIProviderHealthRead,
    AIRunRead,
    AISummaryRequest,
    AIWorkflowPlanRequest,
    AIWorkflowPlanResponse,
)

router = APIRouter()
SessionDependency = Annotated[AsyncSession, Depends(get_session)]
AIUseContext = Annotated[
    RequestContext,
    Depends(require_permission(Permission.AI_USE)),
]
AIReadContext = Annotated[
    RequestContext,
    Depends(require_permission(Permission.AI_READ)),
]
AIFeedbackContext = Annotated[
    RequestContext,
    Depends(require_permission(Permission.AI_FEEDBACK)),
]

service = AIUseCaseService()


def _key(value: str | None, context: RequestContext, use_case: str) -> str:
    cleaned = value.strip() if value else ""
    return cleaned or f"request:{context.correlation_id}:{use_case}"


@router.post(
    "/ai/customer-summary",
    response_model=AICustomerSummaryResponse,
    tags=["ai"],
)
async def customer_summary_endpoint(
    payload: AISummaryRequest,
    session: SessionDependency,
    context: AIUseContext,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> AICustomerSummaryResponse:
    result = await service.execute(
        session,
        context,
        use_case="customer_summary",
        request=payload,
        idempotency_key=_key(idempotency_key, context, "customer_summary"),
    )
    return AICustomerSummaryResponse.model_validate(result)


@router.post(
    "/ai/field-extraction",
    response_model=AIFieldExtractionResponse,
    tags=["ai"],
)
async def field_extraction_endpoint(
    payload: AIExtractionRequest,
    session: SessionDependency,
    context: AIUseContext,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> AIFieldExtractionResponse:
    result = await service.execute(
        session,
        context,
        use_case="field_extraction",
        request=payload,
        idempotency_key=_key(idempotency_key, context, "field_extraction"),
    )
    return AIFieldExtractionResponse.model_validate(result)


@router.post(
    "/ai/next-step-recommendation",
    response_model=AINextStepResponse,
    tags=["ai"],
)
async def next_step_recommendation_endpoint(
    payload: AINextStepRequest,
    session: SessionDependency,
    context: AIUseContext,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> AINextStepResponse:
    result = await service.execute(
        session,
        context,
        use_case="next_step_recommendation",
        request=payload,
        idempotency_key=_key(idempotency_key, context, "next_step_recommendation"),
    )
    return AINextStepResponse.model_validate(result)


@router.post(
    "/ai/communication-draft",
    response_model=AICommunicationDraftResponse,
    tags=["ai"],
)
async def communication_draft_endpoint(
    payload: AICommunicationDraftRequest,
    session: SessionDependency,
    context: AIUseContext,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> AICommunicationDraftResponse:
    result = await service.execute(
        session,
        context,
        use_case="communication_draft",
        request=payload,
        idempotency_key=_key(idempotency_key, context, "communication_draft"),
    )
    return AICommunicationDraftResponse.model_validate(result)


@router.post(
    "/ai/workflow-plan",
    response_model=AIWorkflowPlanResponse,
    tags=["ai"],
)
async def workflow_plan_endpoint(
    payload: AIWorkflowPlanRequest,
    session: SessionDependency,
    context: AIUseContext,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> AIWorkflowPlanResponse:
    result = await service.execute(
        session,
        context,
        use_case="workflow_plan",
        request=payload,
        idempotency_key=_key(idempotency_key, context, "workflow_plan"),
    )
    return AIWorkflowPlanResponse.model_validate(result)


@router.get("/ai/providers/health", response_model=AIProviderHealthRead, tags=["ai"])
async def provider_health_endpoint(context: AIReadContext) -> AIProviderHealthRead:
    _ = context
    return await service.provider_health()


@router.get("/ai/runs", response_model=list[AIRunRead], tags=["ai"])
async def list_ai_runs_endpoint(
    session: SessionDependency,
    context: AIReadContext,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    use_case: str | None = None,
    run_status: str | None = Query(default=None, alias="status"),
) -> list[AIRunRead]:
    runs = await service.list_runs(
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
    return run_read(await service.get_run(session, context, run_id))


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
    feedback = await service.record_feedback(session, context, run_id, payload)
    return feedback_read(feedback)
