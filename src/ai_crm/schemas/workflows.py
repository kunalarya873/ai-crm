from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = [
    "WorkflowAdvance", "WorkflowRead", "WorkflowStart",
]


class WorkflowStart(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow_key: str = Field(min_length=1, max_length=100)
    owner_id: str | None = Field(default=None, max_length=100)
    input_refs: dict[str, object] = Field(default_factory=dict)

    @field_validator("workflow_key", "owner_id")
    @classmethod
    def strip_workflow_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip()


class WorkflowAdvance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approved: bool | None = None
    output: dict[str, object] = Field(default_factory=dict)
    reason: str | None = Field(default=None, max_length=5000)


class WorkflowRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    idempotency_key: str
    workflow_key: str
    status: str
    owner_id: str | None
    current_step: int
    steps: list[str]
    input_refs: dict[str, object]
    outputs: dict[str, object]
    waiting_for: str | None
    error_code: str | None
    error_detail: str | None
    version: int
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
