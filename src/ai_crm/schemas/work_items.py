from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = [
    "WorkItemCreate", "WorkItemRead", "WorkItemTransitionRequest", "WorkItemUpdate",
]


class WorkItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_type: str = Field(default="task", min_length=1, max_length=30)
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=10000)
    priority: int = Field(default=50, ge=0, le=100)
    owner_id: str | None = Field(default=None, max_length=100)
    assignee_id: str | None = Field(default=None, max_length=100)
    team_key: str | None = Field(default=None, max_length=100)
    contact_id: str | None = Field(default=None, max_length=36)
    opportunity_id: str | None = Field(default=None, max_length=36)
    due_at: datetime | None = None
    timezone: str = Field(default="UTC", max_length=64)
    depends_on_ids: list[str] = Field(default_factory=list, max_length=50)
    source: str | None = Field(default=None, max_length=100)

    @field_validator("item_type", "title", "timezone")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must not be blank")
        return cleaned

    @field_validator(
        "description",
        "owner_id",
        "assignee_id",
        "team_key",
        "contact_id",
        "opportunity_id",
        "source",
    )
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class WorkItemUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=10000)
    priority: int | None = Field(default=None, ge=0, le=100)
    owner_id: str | None = Field(default=None, max_length=100)
    assignee_id: str | None = Field(default=None, max_length=100)
    team_key: str | None = Field(default=None, max_length=100)
    due_at: datetime | None = None
    timezone: str | None = Field(default=None, max_length=64)
    depends_on_ids: list[str] | None = Field(default=None, max_length=50)
    source: str | None = Field(default=None, max_length=100)
    archived: bool | None = None

    @field_validator("title", "timezone")
    @classmethod
    def strip_optional_required_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must not be blank")
        return cleaned

    @field_validator("description", "owner_id", "assignee_id", "team_key", "source")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class WorkItemTransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to_status: str = Field(min_length=1, max_length=30)
    reason: str | None = Field(default=None, max_length=5000)
    evidence: str | None = Field(default=None, max_length=10000)

    @field_validator("to_status")
    @classmethod
    def strip_status(cls, value: str) -> str:
        return value.strip()


class WorkItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    item_type: str
    title: str
    description: str | None
    status: str
    priority: int
    owner_id: str | None
    assignee_id: str | None
    team_key: str | None
    contact_id: str | None
    opportunity_id: str | None
    due_at: datetime | None
    timezone: str
    depends_on_ids: list[str]
    completion_evidence: str | None
    blocked_reason: str | None
    source: str | None
    created_by: str
    version: int
    completed_at: datetime | None
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime
