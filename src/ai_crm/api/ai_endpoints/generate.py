from typing import Annotated

from fastapi import Header

from ...schemas import (
    AICommunicationDraftRequest,
    AICommunicationDraftResponse,
    AICustomerSummaryResponse,
    AIExtractionRequest,
    AIFieldExtractionResponse,
    AINextStepRequest,
    AINextStepResponse,
    AISummaryRequest,
    AIWorkflowPlanRequest,
    AIWorkflowPlanResponse,
)
from .base import AIUseContext, SessionDependency, _key, current_service, router

__all__ = [
    "communication_draft_endpoint", "customer_summary_endpoint", "field_extraction_endpoint",
    "next_step_recommendation_endpoint", "workflow_plan_endpoint",
]


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
    result = await current_service().execute(
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
    result = await current_service().execute(
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
    result = await current_service().execute(
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
    result = await current_service().execute(
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
    result = await current_service().execute(
        session,
        context,
        use_case="workflow_plan",
        request=payload,
        idempotency_key=_key(idempotency_key, context, "workflow_plan"),
    )
    return AIWorkflowPlanResponse.model_validate(result)
