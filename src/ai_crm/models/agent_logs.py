from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, utc_now

__all__ = [
    "AgentEvalRun", "AgentMessage",
]


class AgentMessage(Base):
    __tablename__ = "agent_messages"
    __table_args__ = (
        Index("ix_agent_messages_tenant_root", "tenant_id", "root_run_id"),
        Index("ix_agent_messages_tenant_to", "tenant_id", "to_run_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(100), nullable=False)
    root_run_id: Mapped[str] = mapped_column(String(36), nullable=False)
    from_run_id: Mapped[str] = mapped_column(String(36), nullable=False)
    to_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    body: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AgentEvalRun(Base):
    __tablename__ = "agent_eval_runs"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "scenario_key", "strategy", "replay_key", name="uq_agent_eval_runs_replay"
        ),
        Index("ix_agent_eval_runs_tenant_scenario", "tenant_id", "scenario_key"),
        Index("ix_agent_eval_runs_tenant_created", "tenant_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(100), nullable=False)
    scenario_key: Mapped[str] = mapped_column(String(100), nullable=False)
    strategy: Mapped[str] = mapped_column(String(30), nullable=False)
    replay_key: Mapped[str] = mapped_column(String(100), nullable=False)
    task_success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    run_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_by: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
