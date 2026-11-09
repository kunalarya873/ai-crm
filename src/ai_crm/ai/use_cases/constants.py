import hashlib
import json
from typing import Any

from pydantic import BaseModel

from ...schemas import (
    AICommunicationDraftResponse,
    AICustomerSummaryResponse,
    AIFieldExtractionResponse,
    AINextStepResponse,
    AIWorkflowPlanResponse,
)

__all__ = [
    "RESPONSE_MODELS", "USE_CASES", "_request_hash",
]


USE_CASES = frozenset(
    {
        "customer_summary",
        "field_extraction",
        "next_step_recommendation",
        "communication_draft",
        "workflow_plan",
    }
)


RESPONSE_MODELS: dict[str, type[BaseModel]] = {
    "customer_summary": AICustomerSummaryResponse,
    "field_extraction": AIFieldExtractionResponse,
    "next_step_recommendation": AINextStepResponse,
    "communication_draft": AICommunicationDraftResponse,
    "workflow_plan": AIWorkflowPlanResponse,
}


def _request_hash(use_case: str, request: dict[str, Any]) -> str:
    encoded = json.dumps(
        {"use_case": use_case, "request": request},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(encoded.encode()).hexdigest()
