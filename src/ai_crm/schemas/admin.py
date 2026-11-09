from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

__all__ = [
    "AdminUsageRead", "FeatureFlagRead", "FeatureFlagUpdate", "MemberCreate", "MemberRead",
    "MemberUpdate", "SloRead", "SloReport",
]


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
