from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "AIProviderHealthRead", "AlertDecision", "AlertRead", "MetricObservationRead",
    "MetricSummaryItem", "ObservabilitySummary", "OperationalEventRead", "ProactiveCheckResponse",
]


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
