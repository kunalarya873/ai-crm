from datetime import datetime
from typing import Literal

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


class KnowledgeSearchResult(BaseModel):
    chunk_id: str
    text: str
    title: str
    score: float
    freshness: str
    source_id: str
    source_type: str
    source_record_id: str
    source_url: str | None
    source_version: int
    chunk_index: int
    owner_id: str | None
    effective_at: datetime | None
    fresh_until: datetime | None
    citation: dict[str, object]


class KnowledgeSearchResponse(BaseModel):
    query: str
    items: list[KnowledgeSearchResult]
    limit: int
    offset: int
    next_offset: int | None
    insufficient_evidence: bool
    evidence_reason: str | None


class KnowledgeContextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(default="", max_length=500)
    customer_id: str | None = Field(default=None, max_length=100)
    workflow_id: str | None = Field(default=None, max_length=100)
    task_id: str | None = Field(default=None, max_length=100)
    action_type: str | None = Field(default=None, max_length=100)
    source_types: list[str] = Field(default_factory=list, max_length=20)
    max_items: int = Field(default=8, ge=1, le=50)
    max_chars: int = Field(default=12000, ge=100, le=50000)
    include_stale: bool = False

    @field_validator("query", "customer_id", "workflow_id", "task_id", "action_type")
    @classmethod
    def strip_context_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip()


class KnowledgeContextItem(BaseModel):
    chunk_id: str
    text: str
    title: str
    score: float
    freshness: str
    citation: dict[str, object]


class KnowledgeContextResponse(BaseModel):
    assembly_id: str
    query: str
    items: list[KnowledgeContextItem]
    used_chars: int
    max_items: int
    max_chars: int
    truncated: bool
    insufficient_evidence: bool


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


class ReminderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reminder_kind: str = Field(min_length=1, max_length=50)
    scheduled_for: datetime
    timezone: str = Field(default="UTC", max_length=64)

    @field_validator("reminder_kind", "timezone")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must not be blank")
        return cleaned


class ReminderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    work_item_id: str
    reminder_kind: str
    scheduled_for: datetime
    timezone: str
    idempotency_key: str
    status: str
    attempts: int
    delivered_at: datetime | None
    acknowledged_at: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime


class JobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_type: str = Field(min_length=1, max_length=100)
    queue: str = Field(default="default", min_length=1, max_length=100)
    priority: int = Field(default=50, ge=0, le=100)
    payload: dict[str, object] = Field(default_factory=dict)
    run_at: datetime | None = None
    max_attempts: int = Field(default=3, ge=1, le=20)
    backoff_seconds: int = Field(default=30, ge=0, le=3600)
    timeout_seconds: int = Field(default=300, ge=1, le=86400)

    @field_validator("job_type", "queue")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must not be blank")
        return cleaned


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    idempotency_key: str
    request_hash: str
    job_type: str
    queue: str
    trace_id: str | None = None
    priority: int
    payload: dict[str, object]
    status: str
    run_at: datetime
    max_attempts: int
    attempts: int
    backoff_seconds: int
    timeout_seconds: int
    next_attempt_at: datetime | None
    lease_owner: str | None
    lease_expires_at: datetime | None
    heartbeat_at: datetime | None
    timeout_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    result: dict[str, object]
    error_code: str | None
    error_detail: str | None
    created_at: datetime
    updated_at: datetime


class JobClaimRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    worker_id: str = Field(min_length=1, max_length=100)
    lease_seconds: int = Field(default=60, ge=1, le=3600)

    @field_validator("worker_id")
    @classmethod
    def strip_worker_id(cls, value: str) -> str:
        return value.strip()


class JobCompleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result: dict[str, object] = Field(default_factory=dict)


class JobFailureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error_code: str = Field(min_length=1, max_length=100)
    error_detail: str = Field(default="", max_length=500)
    retryable: bool = True


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


class ActionProposalCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_type: str = Field(min_length=1, max_length=100)
    payload: dict[str, object] = Field(default_factory=dict)
    evidence_refs: list[dict[str, object]] = Field(default_factory=list, max_length=50)
    affected_resources: list[dict[str, object]] = Field(default_factory=list, max_length=50)
    intended_changes: dict[str, object] = Field(default_factory=dict)
    expected_side_effects: list[str] = Field(default_factory=list, max_length=20)
    source_ai_run_id: str | None = Field(default=None, max_length=36)
    expires_at: datetime | None = None

    @field_validator("action_type")
    @classmethod
    def strip_action_type(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must not be blank")
        return cleaned


class ActionProposalEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payload: dict[str, object]
    evidence_refs: list[dict[str, object]] | None = Field(default=None, max_length=50)
    affected_resources: list[dict[str, object]] | None = Field(default=None, max_length=50)
    intended_changes: dict[str, object] | None = None
    expected_side_effects: list[str] | None = Field(default=None, max_length=20)
    expires_at: datetime | None = None


class ActionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=5000)


class ActionRecoveryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operator_note: str | None = Field(default=None, max_length=5000)


class ActionProposalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    idempotency_key: str
    request_hash: str
    action_type: str
    action_version: str
    required_permission: str
    risk_level: str
    requires_approval: bool
    status: str
    payload: dict[str, object]
    evidence_refs: list[dict[str, object]]
    affected_resources: list[dict[str, object]]
    intended_changes: dict[str, object]
    expected_side_effects: list[str]
    source_ai_run_id: str | None
    requested_by: str
    last_edited_by: str | None
    approved_by: str | None
    rejected_by: str | None
    approved_at: datetime | None
    expires_at: datetime
    decision_reason: str | None
    last_error_code: str | None
    last_error_detail: str | None
    version: int
    created_at: datetime
    updated_at: datetime


class ActionExecutionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    action_proposal_id: str
    idempotency_key: str
    action_type: str
    request_hash: str
    status: str
    attempts: int
    result: dict[str, object]
    provider_request_id: str | None
    error_code: str | None
    error_detail: str | None
    operator_note: str | None
    uncertain_outcome: bool
    started_at: datetime
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ActionRegistryRead(BaseModel):
    action_type: str
    version: str
    required_permission: str
    risk_level: str
    requires_approval: bool
    timeout_seconds: int
    max_attempts: int
    affected_resource_types: list[str]


class ActionDryRunResponse(BaseModel):
    action_type: str
    action_version: str
    required_permission: str
    risk_level: str
    requires_approval: bool
    valid: bool
    normalized_payload: dict[str, object]
    affected_resources: list[dict[str, object]]
    intended_changes: dict[str, object]
    expected_side_effects: list[str]


class MetricObservationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    metric_key: str
    value: float
    unit: str
    quality: str
    dimensions: dict[str, object]
    source_event_ids: list[str]
    window_start: datetime
    window_end: datetime
    created_at: datetime


class OperationalEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    actor_id: str
    event_type: str
    event_version: str
    operation: str
    resource_type: str
    resource_id: str
    outcome: str
    correlation_id: str
    trace_id: str | None = None
    payload: dict[str, object]
    created_at: datetime


class AlertRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    alert_type: str
    rule_key: str
    rule_version: str
    dedup_key: str
    severity: str
    status: str
    title: str
    description: str
    related_type: str | None
    related_id: str | None
    evidence: list[dict[str, object]]
    work_item_id: str | None
    acknowledged_by: str | None
    acknowledged_at: datetime | None
    resolved_by: str | None
    resolved_at: datetime | None
    resolution_note: str | None
    created_at: datetime
    updated_at: datetime


class AlertDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str | None = Field(default=None, max_length=5000)


class MetricSummaryItem(BaseModel):
    metric_key: str
    value: float
    unit: str
    quality: str
    dimensions: dict[str, object] = Field(default_factory=dict)


class ObservabilitySummary(BaseModel):
    window_start: datetime
    window_end: datetime
    metrics: list[MetricSummaryItem]
    open_alerts: int
    incomplete_metrics: list[str]


class ProactiveCheckResponse(BaseModel):
    checked_at: datetime
    alerts_created: int
    alerts_reopened: int
    work_items_created: int
    suppressed_duplicates: int
    alert_ids: list[str]


class AIProviderHealthRead(BaseModel):
    provider_key: str
    model_key: str
    status: Literal["healthy", "unhealthy"]
    detail: str


class MemberCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=320)
    role: str = Field(min_length=1, max_length=30)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class MemberUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str | None = Field(default=None, min_length=1, max_length=30)
    is_active: bool | None = None

    @model_validator(mode="after")
    def require_a_change(self) -> "MemberUpdate":
        if self.role is None and self.is_active is None:
            raise ValueError("At least one of role or is_active is required")
        return self


class MemberRead(BaseModel):
    id: str
    user_id: str
    email: str
    display_name: str
    role: str
    is_active: bool
    version: int
    created_at: datetime


AgentCapability = Literal["read", "propose", "delegate", "escalate"]
RiskLevel = Literal["low", "medium", "high"]
EscalationReason = Literal[
    "uncertainty",
    "policy_denial",
    "missing_context",
    "sensitive_action",
    "conflicting_outputs",
    "budget_exhausted",
    "repeated_failure",
    "deadline_exceeded",
]


class AgentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{1,99}$")
    name: str = Field(min_length=1, max_length=200)
    purpose: str = Field(min_length=1, max_length=2000)
    agent_version: str = Field(default="v1", min_length=1, max_length=50)
    owner_id: str | None = Field(default=None, max_length=100)
    allowed_capabilities: list[AgentCapability] = Field(default_factory=list, max_length=4)
    allowed_actions: list[str] = Field(default_factory=list, max_length=20)
    allow_sensitive: bool = False
    risk_ceiling: RiskLevel = "low"
    max_depth: int = Field(default=1, ge=0)
    max_fanout: int = Field(default=2, ge=0)
    token_budget: int = Field(default=20000, ge=1)
    step_budget: int = Field(default=20, ge=1)
    side_effect_budget: int = Field(default=3, ge=0)

    @field_validator("name", "purpose")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must not be blank")
        return cleaned


class AgentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    purpose: str | None = Field(default=None, min_length=1, max_length=2000)
    agent_version: str | None = Field(default=None, min_length=1, max_length=50)
    allowed_capabilities: list[AgentCapability] | None = Field(default=None, max_length=4)
    allowed_actions: list[str] | None = Field(default=None, max_length=20)
    allow_sensitive: bool | None = None
    risk_ceiling: RiskLevel | None = None
    max_depth: int | None = Field(default=None, ge=0)
    max_fanout: int | None = Field(default=None, ge=0)
    token_budget: int | None = Field(default=None, ge=1)
    step_budget: int | None = Field(default=None, ge=1)
    side_effect_budget: int | None = Field(default=None, ge=0)
    status: Literal["active", "suspended", "retired"] | None = None

    @model_validator(mode="after")
    def require_a_change(self) -> "AgentUpdate":
        if not self.model_fields_set:
            raise ValueError("at least one field must be provided")
        return self


class AgentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    key: str
    name: str
    purpose: str
    agent_version: str
    owner_id: str
    allowed_capabilities: list[str]
    allowed_actions: list[str]
    allow_sensitive: bool
    risk_ceiling: str
    max_depth: int
    max_fanout: int
    token_budget: int
    step_budget: int
    side_effect_budget: int
    status: str
    version: int
    created_at: datetime
    updated_at: datetime


class AgentRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(min_length=1, max_length=36)
    objective: str = Field(min_length=1, max_length=500)
    expected_result: str | None = Field(default=None, max_length=1000)
    deadline_at: datetime
    work_item_id: str | None = Field(default=None, max_length=36)
    token_budget: int | None = Field(default=None, ge=1)
    step_budget: int | None = Field(default=None, ge=1)
    side_effect_budget: int | None = Field(default=None, ge=0)

    @field_validator("objective")
    @classmethod
    def strip_objective(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must not be blank")
        return cleaned


class DelegationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_key: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=1, max_length=1000)
    objective: str = Field(min_length=1, max_length=500)
    expected_result: str = Field(min_length=1, max_length=1000)
    deadline_at: datetime
    token_budget: int = Field(ge=1)
    step_budget: int = Field(ge=1)
    side_effect_budget: int = Field(default=0, ge=0)


class EscalationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: EscalationReason
    summary: str = Field(min_length=1, max_length=2000)
    evidence_refs: list[dict[str, object]] = Field(default_factory=list, max_length=50)
    proposed_next_steps: list[str] = Field(default_factory=list, max_length=10)


class OutputInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: Literal["success", "failed"] = "success"
    summary: str = Field(min_length=1, max_length=4000)
    result: dict[str, object] = Field(default_factory=dict)


class AgentStepCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_key: str = Field(min_length=1, max_length=200)
    step_type: Literal["retrieve", "propose", "delegate", "escalate", "output"]
    input: dict[str, object] = Field(default_factory=dict)
    tokens: int = Field(default=0, ge=0, le=1_000_000)


class AgentRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    agent_id: str
    agent_key: str
    agent_version: str
    parent_run_id: str | None
    root_run_id: str
    depth: int
    max_depth: int
    max_fanout: int
    owner_id: str
    objective: str
    expected_result: str | None
    deadline_at: datetime
    work_item_id: str | None
    token_budget: int
    tokens_used: int
    step_budget: int
    steps_used: int
    side_effect_budget: int
    side_effects_used: int
    status: str
    terminal_reason: str | None
    escalation_work_item_id: str | None
    escalation_reason: str | None
    trace_id: str | None
    version: int
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AgentStepRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    run_id: str
    seq: int
    step_key: str
    step_type: str
    status: str
    input: dict[str, object]
    output: dict[str, object]
    action_proposal_id: str | None
    child_run_id: str | None
    context_assembly_id: str | None
    tokens: int
    error_code: str | None
    created_at: datetime


class AgentStepResult(BaseModel):
    step: AgentStepRead
    run: AgentRunRead


class AgentRunDetail(AgentRunRead):
    steps: list[AgentStepRead]


class AgentMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    root_run_id: str
    from_run_id: str
    to_run_id: str | None
    kind: str
    body: dict[str, object]
    created_at: datetime


class AgentEvalRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_key: str | None = Field(default=None, max_length=100)
    replay_key: str = Field(min_length=1, max_length=100)


class AgentEvalScenarioRead(BaseModel):
    key: str
    description: str
    objective: str
    expected_proposals: int
    expected_escalation: str | None
    human_baseline_minutes: int
    human_baseline_interventions: int
    human_baseline_is_assumption: bool


class AgentEvalResultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    scenario_key: str
    strategy: str
    replay_key: str
    task_success: bool
    metrics: dict[str, object]
    run_ids: list[str]
    created_by: str
    created_at: datetime


class AgentEvalComparison(BaseModel):
    scenario_key: str
    description: str
    strategies: dict[str, dict[str, object]]
    deltas_multi_minus_single: dict[str, float | None]
    assumptions: list[str]


class AgentEvalReport(BaseModel):
    replay_key: str
    comparisons: list[AgentEvalComparison]
    aggregate: dict[str, dict[str, int]]
    assumptions: list[str]


class FeatureFlagUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    reason: str | None = Field(default=None, max_length=500)


class FeatureFlagRead(BaseModel):
    flag: str
    enabled: bool
    source: Literal["default", "tenant", "platform"]
    reason: str | None
    version: int
    updated_by: str | None = None
    updated_at: datetime | None = None


class SloRead(BaseModel):
    key: str
    description: str
    unit: str
    comparison: Literal["lte", "gte"]
    target: float
    owner: str
    status: Literal["met", "breached", "no_data", "not_measured"]
    value: float | None
    detail: dict[str, object]
    reason: str | None


class SloReport(BaseModel):
    window_start: datetime
    window_end: datetime
    slos: list[SloRead]


class AdminUsageRead(BaseModel):
    members_by_role: dict[str, int]
    connections_by_status: dict[str, int]
    jobs_by_status: dict[str, int]
    ai_runs: dict[str, int]
    action_proposals_by_status: dict[str, int]
    action_executions_by_status: dict[str, int]
    agent_runs_by_status: dict[str, int]
    open_alerts: int
    capabilities: list[FeatureFlagRead]
