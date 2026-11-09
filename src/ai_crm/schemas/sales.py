from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = [
    "CompanyCreate", "CompanyRead", "CompanyUpdate", "OpportunityCreate", "OpportunityRead",
    "OpportunityUpdate",
]


class CompanyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    status: str = Field(default="prospect", min_length=1, max_length=30)
    owner_id: str | None = Field(default=None, max_length=100)

    @field_validator("name", "status")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must not be blank")
        return cleaned


class CompanyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    status: str | None = Field(default=None, min_length=1, max_length=30)
    owner_id: str | None = Field(default=None, max_length=100)
    archived: bool | None = None

    @field_validator("name", "status")
    @classmethod
    def strip_optional_required_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must not be blank")
        return cleaned


class CompanyRead(CompanyCreate):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    normalized_name: str
    owner_id: str | None = None
    archived_at: datetime | None
    version: int
    created_at: datetime
    updated_at: datetime


class OpportunityCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    company_id: str | None = Field(default=None, max_length=36)
    contact_id: str | None = Field(default=None, max_length=36)
    stage: str = Field(default="qualification", min_length=1, max_length=30)
    status: str = Field(default="open", min_length=1, max_length=30)
    priority: str = Field(default="normal", min_length=1, max_length=30)
    owner_id: str | None = Field(default=None, max_length=100)
    next_step: str | None = Field(default=None, max_length=500)
    expected_close_at: datetime | None = None

    @field_validator("name", "stage", "status", "priority")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must not be blank")
        return cleaned

    @field_validator("company_id", "contact_id", "owner_id", "next_step")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class OpportunityUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    company_id: str | None = Field(default=None, max_length=36)
    contact_id: str | None = Field(default=None, max_length=36)
    stage: str | None = Field(default=None, min_length=1, max_length=30)
    status: str | None = Field(default=None, min_length=1, max_length=30)
    priority: str | None = Field(default=None, min_length=1, max_length=30)
    owner_id: str | None = Field(default=None, max_length=100)
    next_step: str | None = Field(default=None, max_length=500)
    expected_close_at: datetime | None = None
    win_loss_reason: str | None = Field(default=None, max_length=500)
    archived: bool | None = None

    @field_validator("name", "stage", "status", "priority")
    @classmethod
    def strip_optional_required_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must not be blank")
        return cleaned

    @field_validator(
        "company_id",
        "contact_id",
        "owner_id",
        "next_step",
        "win_loss_reason",
    )
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class OpportunityRead(OpportunityCreate):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    win_loss_reason: str | None
    archived_at: datetime | None
    version: int
    created_at: datetime
    updated_at: datetime
