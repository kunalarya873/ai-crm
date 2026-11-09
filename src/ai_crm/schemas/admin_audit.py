from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "AgentEvalComparison", "AgentEvalReport", "AgentEvalResultRead", "AgentEvalRunRequest",
    "AgentEvalScenarioRead", "AuditEventRead", "RetentionPurgeRequest", "RetentionPurgeResult",
]


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


class AuditEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    actor_id: str
    action: str
    entity_type: str
    entity_id: str
    outcome: str
    reason: str | None
    correlation_id: str
    details: dict[str, Any]
    created_at: datetime


class RetentionPurgeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    older_than_days: int | None = Field(default=None, ge=1, le=3650)
    dry_run: bool = True


class RetentionPurgeResult(BaseModel):
    dry_run: bool
    cutoff: datetime
    older_than_days: int
    counts: dict[str, int]
    batch_limit: int
    truncated: bool
    legal_hold_active: bool = False
