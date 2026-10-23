from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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


class IntegrationConnectionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_key: str = Field(min_length=1, max_length=50)
    external_account_id: str = Field(min_length=1, max_length=200)
    scopes: list[str] = Field(default_factory=list, max_length=50)
    secret_ref: str = Field(min_length=1, max_length=500)
    configuration: dict[str, object] = Field(default_factory=dict)

    @field_validator("provider_key", "external_account_id", "secret_ref")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must not be blank")
        return cleaned


class IntegrationConnectionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    provider_key: str
    external_account_id: str
    status: str
    scopes: list[str]
    token_expires_at: datetime | None
    last_tested_at: datetime | None
    last_error_code: str | None
    created_at: datetime
    updated_at: datetime


class IntegrationSyncRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    connection_id: str
    resource_type: str
    mode: str
    status: str
    cursor: str | None
    started_at: datetime | None
    finished_at: datetime | None
    last_attempt_at: datetime | None
    last_success_at: datetime | None
    records_processed: int
    retry_count: int
    next_retry_at: datetime | None
    failure_code: str | None
    failure_detail: str | None
    created_at: datetime


class IntegrationRecordLinkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    connection_id: str
    resource_type: str
    provider_record_id: str
    canonical_type: str
    canonical_id: str
    source_url: str | None
    provider_updated_at: datetime | None
    last_seen_at: datetime
    deleted_at: datetime | None
    provenance: dict[str, object]


class ExternalWriteCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: str = Field(min_length=1, max_length=100)
    payload: dict[str, object] = Field(default_factory=dict)

    @field_validator("operation")
    @classmethod
    def strip_operation(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must not be blank")
        return cleaned


class ExternalWriteRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    connection_id: str
    idempotency_key: str
    operation: str
    request_hash: str
    status: str
    provider_request_id: str | None
    response_metadata: dict[str, object]
    attempts: int
    last_error: str | None
    created_at: datetime
    updated_at: datetime


class WebhookAccepted(BaseModel):
    id: str
    provider_event_id: str
    status: str
