from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

__all__ = [
    "AgentCapability", "AgentCreate", "AgentRead", "AgentUpdate", "EscalationReason", "RiskLevel",
]


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
