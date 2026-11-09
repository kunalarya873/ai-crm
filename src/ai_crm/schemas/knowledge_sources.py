from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = [
    "KnowledgeIndexJobRead", "KnowledgeSourceCreate", "KnowledgeSourceRead",
    "KnowledgeSourceUpdate",
]


class KnowledgeSourceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_type: str = Field(min_length=1, max_length=50)
    source_record_id: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=300)
    content: str = Field(default="", max_length=100000)
    source_url: str | None = Field(default=None, max_length=1000)
    owner_id: str | None = Field(default=None, max_length=100)
    visibility: str = Field(default="tenant", max_length=30)
    allowed_user_ids: list[str] = Field(default_factory=list, max_length=100)
    customer_id: str | None = Field(default=None, max_length=100)
    searchable: bool = True
    ai_allowed: bool = True
    sensitivity: str = Field(default="normal", max_length=30)
    effective_at: datetime | None = None
    fresh_until: datetime | None = None

    @field_validator(
        "source_type",
        "source_record_id",
        "title",
        "visibility",
        "sensitivity",
    )
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must not be blank")
        return cleaned

    @field_validator("content", "source_url", "owner_id", "customer_id")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip()


class KnowledgeSourceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=300)
    content: str | None = Field(default=None, max_length=100000)
    source_url: str | None = Field(default=None, max_length=1000)
    owner_id: str | None = Field(default=None, max_length=100)
    visibility: str | None = Field(default=None, max_length=30)
    allowed_user_ids: list[str] | None = Field(default=None, max_length=100)
    customer_id: str | None = Field(default=None, max_length=100)
    searchable: bool | None = None
    ai_allowed: bool | None = None
    sensitivity: str | None = Field(default=None, max_length=30)
    effective_at: datetime | None = None
    fresh_until: datetime | None = None
    archived: bool | None = None

    @field_validator("title", "visibility", "sensitivity")
    @classmethod
    def strip_optional_required_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must not be blank")
        return cleaned

    @field_validator("content", "source_url", "owner_id", "customer_id")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip()


class KnowledgeSourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    source_type: str
    source_record_id: str
    title: str
    content: str
    source_url: str | None
    owner_id: str | None
    visibility: str
    allowed_user_ids: list[str]
    customer_id: str | None
    status: str
    searchable: bool
    ai_allowed: bool
    sensitivity: str
    version: int
    effective_at: datetime | None
    fresh_until: datetime | None
    source_updated_at: datetime | None
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


class KnowledgeIndexJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    source_id: str
    source_version: int
    status: str
    attempts: int
    lease_owner: str | None
    lease_expires_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    indexed_chunks: int
    failure_code: str | None
    failure_detail: str | None
    created_at: datetime
