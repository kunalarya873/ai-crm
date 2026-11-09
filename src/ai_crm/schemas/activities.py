from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

__all__ = [
    "ActivityCreate", "ActivityRead", "TimelineEntry",
]


class ActivityCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str = Field(min_length=1, max_length=30)
    subject: str = Field(min_length=1, max_length=200)
    body: str | None = Field(default=None, max_length=10000)
    event_at: datetime | None = None
    contact_id: str | None = Field(default=None, max_length=36)
    company_id: str | None = Field(default=None, max_length=36)
    opportunity_id: str | None = Field(default=None, max_length=36)
    source_system: str | None = Field(default=None, max_length=100)
    source_record_id: str | None = Field(default=None, max_length=200)

    @field_validator("kind", "subject")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must not be blank")
        return cleaned

    @field_validator(
        "body",
        "contact_id",
        "company_id",
        "opportunity_id",
        "source_system",
        "source_record_id",
    )
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @model_validator(mode="after")
    def require_related_record(self) -> "ActivityCreate":
        if not any((self.contact_id, self.company_id, self.opportunity_id)):
            raise ValueError("an activity must be linked to a contact, company, or opportunity")
        return self


class ActivityRead(ActivityCreate):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    ingested_at: datetime
    actor_id: str | None


class TimelineEntry(BaseModel):
    id: str
    type: str
    title: str
    body: str | None
    occurred_at: datetime
    status: str | None
    actor_id: str | None
    source: str | None
