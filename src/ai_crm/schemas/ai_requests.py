from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = [
    "AICommunicationDraftRequest", "AIContextRequest", "AIExtractionRequest", "AINextStepRequest",
    "AISummaryRequest", "AIWorkflowPlanRequest",
]


class AIContextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(default="", max_length=500)
    customer_id: str | None = Field(default=None, max_length=100)
    workflow_id: str | None = Field(default=None, max_length=100)
    task_id: str | None = Field(default=None, max_length=100)
    source_types: list[str] = Field(default_factory=list, max_length=20)
    max_items: int = Field(default=8, ge=1, le=30)
    max_chars: int = Field(default=12000, ge=100, le=30000)
    include_stale: bool = False

    @field_validator("query", "customer_id", "workflow_id", "task_id")
    @classmethod
    def strip_context_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip()


class AISummaryRequest(AIContextRequest):
    focus: str | None = Field(default=None, max_length=500)

    @field_validator("focus")
    @classmethod
    def strip_focus(cls, value: str | None) -> str | None:
        return value.strip() if value else None


class AIExtractionRequest(AIContextRequest):
    text: str | None = Field(default=None, max_length=10000)
    fields: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("text")
    @classmethod
    def strip_extraction_text(cls, value: str | None) -> str | None:
        return value.strip() if value else None

    @field_validator("fields")
    @classmethod
    def validate_extraction_fields(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value if item.strip()]
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("fields must be unique")
        return cleaned


class AINextStepRequest(AIContextRequest):
    goal: str | None = Field(default=None, max_length=1000)

    @field_validator("goal")
    @classmethod
    def strip_goal(cls, value: str | None) -> str | None:
        return value.strip() if value else None


class AICommunicationDraftRequest(AIContextRequest):
    channel: Literal["email", "message", "call_script"] = "email"
    purpose: str = Field(min_length=1, max_length=500)
    recipient_name: str | None = Field(default=None, max_length=200)
    tone: Literal["professional", "concise", "warm"] = "professional"

    @field_validator("purpose", "recipient_name")
    @classmethod
    def strip_communication_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must not be blank")
        return cleaned


class AIWorkflowPlanRequest(AIContextRequest):
    objective: str = Field(min_length=1, max_length=1000)
    allowed_action_types: list[str] = Field(
        default_factory=lambda: ["create_work_item", "request_approval"],
        max_length=10,
    )

    @field_validator("objective")
    @classmethod
    def strip_objective(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must not be blank")
        return cleaned

    @field_validator("allowed_action_types")
    @classmethod
    def validate_allowed_action_types(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value if item.strip()]
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("allowed_action_types must be unique")
        return cleaned
