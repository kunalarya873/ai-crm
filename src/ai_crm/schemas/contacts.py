from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = [
    "ContactCreate", "ContactRead", "ContactUpdate", "HealthResponse",
]


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


class ContactCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    email: str | None = Field(default=None, max_length=320)
    company_name: str | None = Field(default=None, max_length=200)
    company_id: str | None = Field(default=None, max_length=36)
    status: str = Field(default="lead", min_length=1, max_length=30)
    owner_id: str | None = Field(default=None, max_length=100)

    @field_validator("first_name", "last_name", "status")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must not be blank")
        return cleaned

    @field_validator("email", "company_name", "company_id", "owner_id")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class ContactRead(ContactCreate):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None
    version: int


class ContactUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, min_length=1, max_length=100)
    email: str | None = Field(default=None, max_length=320)
    company_name: str | None = Field(default=None, max_length=200)
    company_id: str | None = Field(default=None, max_length=36)
    status: str | None = Field(default=None, min_length=1, max_length=30)
    owner_id: str | None = Field(default=None, max_length=100)
    archived: bool | None = None

    @field_validator("first_name", "last_name", "status")
    @classmethod
    def strip_optional_required_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must not be blank")
        return cleaned

    @field_validator("email", "company_name", "company_id", "owner_id")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None
