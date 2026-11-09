from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = [
    "ActionDecision", "ActionDryRunResponse", "ActionExecutionRead", "ActionProposalCreate",
    "ActionProposalEdit", "ActionProposalRead", "ActionRecoveryRequest", "ActionRegistryRead",
]


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
