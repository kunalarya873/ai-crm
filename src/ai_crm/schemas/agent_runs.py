from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .agents import EscalationReason

__all__ = [
    "AgentMessageRead", "AgentRunCreate", "AgentRunDetail", "AgentRunRead", "AgentStepCreate",
    "AgentStepRead", "AgentStepResult", "DelegationInput", "EscalationInput", "OutputInput",
]


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
