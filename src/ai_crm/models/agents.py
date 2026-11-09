from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, utc_now

__all__ = [
    "Agent", "AgentRun", "AgentStep",
]


class Agent(Base):
    __tablename__ = "agents"
    __table_args__ = (
        UniqueConstraint("tenant_id", "key", name="uq_agents_tenant_key"),
        Index("ix_agents_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(100), nullable=False)
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    agent_version: Mapped[str] = mapped_column(String(50), nullable=False)
    owner_id: Mapped[str] = mapped_column(String(100), nullable=False)
    allowed_capabilities: Mapped[list[str]] = mapped_column(JSON, default=list)
    allowed_actions: Mapped[list[str]] = mapped_column(JSON, default=list)
    allow_sensitive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    risk_ceiling: Mapped[str] = mapped_column(String(30), nullable=False, default="low")
    max_depth: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    max_fanout: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    token_budget: Mapped[int] = mapped_column(Integer, nullable=False)
    step_budget: Mapped[int] = mapped_column(Integer, nullable=False)
    side_effect_budget: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class AgentRun(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_agent_runs_tenant_idempotency"),
        Index("ix_agent_runs_tenant_status", "tenant_id", "status"),
        Index("ix_agent_runs_tenant_root", "tenant_id", "root_run_id"),
        Index("ix_agent_runs_tenant_parent", "tenant_id", "parent_run_id"),
        Index("ix_agent_runs_tenant_created", "tenant_id", "created_at"),
        Index("ix_agent_runs_status_deadline", "status", "deadline_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(100), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    agent_id: Mapped[str] = mapped_column(String(36), nullable=False)
    agent_key: Mapped[str] = mapped_column(String(100), nullable=False)
    agent_version: Mapped[str] = mapped_column(String(50), nullable=False)
    parent_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    root_run_id: Mapped[str] = mapped_column(String(36), nullable=False)
    depth: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_depth: Mapped[int] = mapped_column(Integer, nullable=False)
    max_fanout: Mapped[int] = mapped_column(Integer, nullable=False)
    owner_id: Mapped[str] = mapped_column(String(100), nullable=False)
    objective: Mapped[str] = mapped_column(String(500), nullable=False)
    objective_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    expected_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    work_item_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    token_budget: Mapped[int] = mapped_column(Integer, nullable=False)
    tokens_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    step_budget: Mapped[int] = mapped_column(Integer, nullable=False)
    steps_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    side_effect_budget: Mapped[int] = mapped_column(Integer, nullable=False)
    side_effects_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="running")
    terminal_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    escalation_work_item_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    escalation_reason: Mapped[str | None] = mapped_column(String(50), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class AgentStep(Base):
    __tablename__ = "agent_steps"
    __table_args__ = (
        UniqueConstraint("run_id", "step_key", name="uq_agent_steps_run_key"),
        UniqueConstraint("run_id", "seq", name="uq_agent_steps_run_seq"),
        Index("ix_agent_steps_tenant_run", "tenant_id", "run_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(100), nullable=False)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    step_key: Mapped[str] = mapped_column(String(200), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    step_type: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    input: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    output: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    action_proposal_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    child_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    context_assembly_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
