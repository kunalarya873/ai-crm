from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = [
    "AIActionProposal", "AICommunicationDraftResponse", "AICustomerSummaryResponse",
    "AIEvidenceReference", "AIFeedbackCreate", "AIFeedbackRead", "AIFieldExtractionResponse",
    "AINextStepResponse", "AIResponseMetadata", "AIRunRead", "AIWorkflowPlanResponse",
    "AIWorkflowPlanStep",
]


class AIEvidenceReference(BaseModel):
    reference_type: str
    reference_id: str
    citation: dict[str, object] = Field(default_factory=dict)


class AIResponseMetadata(BaseModel):
    run_id: str
    status: Literal["succeeded", "fallback", "failed"]
    provider_key: str
    model_key: str
    prompt_version: str
    context_assembly_id: str | None
    confidence: float = Field(ge=0, le=1)
    uncertainty: list[str]
    evidence: list[AIEvidenceReference]
    insufficient_evidence: bool
    fallback_reason: str | None


class AICustomerSummaryResponse(AIResponseMetadata):
    summary: str
    key_points: list[str]


class AIFieldExtractionResponse(AIResponseMetadata):
    fields: dict[str, object]
    missing_fields: list[str]


class AINextStepResponse(AIResponseMetadata):
    recommendation: str
    rationale: str
    priority: Literal["low", "normal", "high"]
    proposed_work_item: dict[str, object] | None


class AICommunicationDraftResponse(AIResponseMetadata):
    channel: Literal["email", "message", "call_script"]
    subject: str | None
    body: str
    draft_only: Literal[True] = True
    requires_human_review: Literal[True] = True


class AIWorkflowPlanStep(BaseModel):
    step_key: str
    title: str
    rationale: str
    requires_approval: Literal[True] = True


class AIActionProposal(BaseModel):
    action_type: Literal["create_work_item", "request_approval"]
    parameters: dict[str, object]
    requires_approval: Literal[True] = True


class AIWorkflowPlanResponse(AIResponseMetadata):
    objective: str
    steps: list[AIWorkflowPlanStep]
    proposed_actions: list[AIActionProposal]


class AIRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    actor_id: str
    idempotency_key: str
    request_hash: str
    use_case: str
    provider_key: str
    model_key: str
    config_version: str
    prompt_version: str
    prompt_hash: str
    feature_flag: str
    context_assembly_id: str | None
    context_refs: list[dict[str, object]]
    request: dict[str, object]
    status: str
    validation_status: str
    output: dict[str, object]
    output_text: str | None
    evidence_refs: list[dict[str, object]]
    confidence: float | None
    uncertainty: list[str]
    input_tokens: int
    output_tokens: int
    total_tokens: int
    provider_attempts: int
    estimated_cost_micros: int
    latency_ms: int | None
    error_code: str | None
    error_detail: str | None
    fallback_reason: str | None
    started_at: datetime
    completed_at: datetime | None
    created_at: datetime


class AIFeedbackCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feedback_type: Literal["accepted", "rejected", "edited", "corrected"]
    edited_output: dict[str, object] | None = None
    correction_note: str | None = Field(default=None, max_length=5000)

    @model_validator(mode="after")
    def validate_feedback(self) -> "AIFeedbackCreate":
        if self.feedback_type in {"edited", "corrected"} and self.edited_output is None:
            raise ValueError("edited_output is required for edited or corrected feedback")
        return self


class AIFeedbackRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    ai_run_id: str
    actor_id: str
    feedback_type: str
    edited_output: dict[str, object] | None
    correction_note: str | None
    created_at: datetime
