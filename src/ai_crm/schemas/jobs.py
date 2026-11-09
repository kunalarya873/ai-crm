from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = [
    "JobClaimRequest", "JobCompleteRequest", "JobCreate", "JobFailureRequest", "JobRead",
    "ReminderCreate", "ReminderRead",
]


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
