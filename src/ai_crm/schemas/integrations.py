from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = [
    "ExternalWriteCreate", "ExternalWriteRead", "IntegrationConnectionCreate",
    "IntegrationConnectionRead", "IntegrationRecordLinkRead", "IntegrationSyncRunRead",
    "WebhookAccepted",
]


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
