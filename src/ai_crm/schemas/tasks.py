from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = [
    "TaskCreate", "TaskRead", "TaskUpdate",
]


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    status: str = Field(default="open", min_length=1, max_length=30)
    priority: str = Field(default="normal", min_length=1, max_length=30)
    assignee_id: str | None = Field(default=None, max_length=100)
    contact_id: str | None = Field(default=None, max_length=36)
    opportunity_id: str | None = Field(default=None, max_length=36)
    due_at: datetime | None = None
    completion_evidence: str | None = Field(default=None, max_length=5000)
    source: str | None = Field(default=None, max_length=100)

    @field_validator("title", "status")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must not be blank")
        return cleaned

    @field_validator(
        "description",
        "assignee_id",
        "contact_id",
        "opportunity_id",
        "completion_evidence",
        "source",
    )
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class TaskRead(TaskCreate):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    archived_at: datetime | None
    version: int


class TaskUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    status: str | None = Field(default=None, min_length=1, max_length=30)
    priority: str | None = Field(default=None, min_length=1, max_length=30)
    assignee_id: str | None = Field(default=None, max_length=100)
    contact_id: str | None = Field(default=None, max_length=36)
    opportunity_id: str | None = Field(default=None, max_length=36)
    due_at: datetime | None = None
    completion_evidence: str | None = Field(default=None, max_length=5000)
    archived: bool | None = None

    @field_validator("title", "status", "priority")
    @classmethod
    def strip_optional_required_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must not be blank")
        return cleaned

    @field_validator(
        "description",
        "assignee_id",
        "contact_id",
        "opportunity_id",
        "completion_evidence",
    )
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None
