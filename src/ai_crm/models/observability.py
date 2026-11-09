from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, Float, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, utc_now

__all__ = [
    "MetricObservation", "OperationalAlert", "OperationalEvent", "RequestMetricBucket",
]


class OperationalEvent(Base):
    __tablename__ = "operational_events"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "event_type",
            "dedup_key",
            name="uq_operational_events_dedup",
        ),
        Index("ix_operational_events_tenant_created", "tenant_id", "created_at"),
        Index("ix_operational_events_tenant_type", "tenant_id", "event_type", "created_at"),
        Index("ix_operational_events_correlation", "correlation_id"),
        Index("ix_operational_events_trace", "tenant_id", "trace_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(100), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(100), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    event_version: Mapped[str] = mapped_column(String(30), nullable=False, default="v1")
    operation: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(100), nullable=False)
    outcome: Mapped[str] = mapped_column(String(30), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(100), nullable=False)
    trace_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    dedup_key: Mapped[str | None] = mapped_column(String(300), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class MetricObservation(Base):
    __tablename__ = "metric_observations"
    __table_args__ = (
        Index("ix_metric_observations_tenant_key_window", "tenant_id", "metric_key", "window_end"),
        Index("ix_metric_observations_tenant_created", "tenant_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(100), nullable=False)
    metric_key: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(30), nullable=False, default="count")
    quality: Mapped[str] = mapped_column(String(30), nullable=False, default="complete")
    dimensions: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source_event_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class OperationalAlert(Base):
    __tablename__ = "operational_alerts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "dedup_key", name="uq_operational_alerts_dedup"),
        Index("ix_operational_alerts_tenant_status", "tenant_id", "status"),
        Index("ix_operational_alerts_tenant_created", "tenant_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(100), nullable=False)
    alert_type: Mapped[str] = mapped_column(String(30), nullable=False)
    rule_key: Mapped[str] = mapped_column(String(100), nullable=False)
    rule_version: Mapped[str] = mapped_column(String(30), nullable=False, default="v1")
    dedup_key: Mapped[str] = mapped_column(String(300), nullable=False)
    severity: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="open")
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    related_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    related_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    work_item_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    acknowledged_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class RequestMetricBucket(Base):
    """Per-minute request counts and a latency histogram for one process; summed when read.
    The empty tenant holds requests that never reached an authenticated tenant."""

    __tablename__ = "request_metric_buckets"
    __table_args__ = (Index("ix_request_metric_buckets_tenant_start", "tenant_id", "bucket_start"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(100), nullable=False)
    bucket_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    route: Mapped[str] = mapped_column(String(200), nullable=False)
    method: Mapped[str] = mapped_column(String(10), nullable=False)
    status_class: Mapped[str] = mapped_column(String(10), nullable=False)
    process_id: Mapped[str] = mapped_column(String(60), nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_sum_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    le_25: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    le_50: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    le_100: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    le_250: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    le_500: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    le_1000: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    le_2500: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    le_5000: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    le_inf: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
