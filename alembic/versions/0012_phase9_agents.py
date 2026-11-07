"""add multi-agent coordination tables

Revision ID: 0012_phase9_agents
Revises: 0011_phase8_trace_context
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0012_phase9_agents"
down_revision: str | None = "0011_phase8_trace_context"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(100), nullable=False),
        sa.Column("key", sa.String(100), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("agent_version", sa.String(50), nullable=False),
        sa.Column("owner_id", sa.String(100), nullable=False),
        sa.Column("allowed_capabilities", sa.JSON(), nullable=False),
        sa.Column("allowed_actions", sa.JSON(), nullable=False),
        sa.Column("allow_sensitive", sa.Boolean(), nullable=False),
        sa.Column("risk_ceiling", sa.String(30), nullable=False),
        sa.Column("max_depth", sa.Integer(), nullable=False),
        sa.Column("max_fanout", sa.Integer(), nullable=False),
        sa.Column("token_budget", sa.Integer(), nullable=False),
        sa.Column("step_budget", sa.Integer(), nullable=False),
        sa.Column("side_effect_budget", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "key", name="uq_agents_tenant_key"),
    )
    op.create_index("ix_agents_tenant_status", "agents", ["tenant_id", "status"])

    op.create_table(
        "agent_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(100), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("request_hash", sa.String(128), nullable=False),
        sa.Column("agent_id", sa.String(36), nullable=False),
        sa.Column("agent_key", sa.String(100), nullable=False),
        sa.Column("agent_version", sa.String(50), nullable=False),
        sa.Column("parent_run_id", sa.String(36), nullable=True),
        sa.Column("root_run_id", sa.String(36), nullable=False),
        sa.Column("depth", sa.Integer(), nullable=False),
        sa.Column("max_depth", sa.Integer(), nullable=False),
        sa.Column("max_fanout", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.String(100), nullable=False),
        sa.Column("objective", sa.String(500), nullable=False),
        sa.Column("objective_hash", sa.String(128), nullable=False),
        sa.Column("expected_result", sa.Text(), nullable=True),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("work_item_id", sa.String(36), nullable=True),
        sa.Column("token_budget", sa.Integer(), nullable=False),
        sa.Column("tokens_used", sa.Integer(), nullable=False),
        sa.Column("step_budget", sa.Integer(), nullable=False),
        sa.Column("steps_used", sa.Integer(), nullable=False),
        sa.Column("side_effect_budget", sa.Integer(), nullable=False),
        sa.Column("side_effects_used", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("terminal_reason", sa.String(100), nullable=True),
        sa.Column("escalation_work_item_id", sa.String(36), nullable=True),
        sa.Column("escalation_reason", sa.String(50), nullable=True),
        sa.Column("trace_id", sa.String(32), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "tenant_id", "idempotency_key", name="uq_agent_runs_tenant_idempotency"
        ),
    )
    op.create_index("ix_agent_runs_tenant_status", "agent_runs", ["tenant_id", "status"])
    op.create_index("ix_agent_runs_tenant_root", "agent_runs", ["tenant_id", "root_run_id"])
    op.create_index(
        "ix_agent_runs_tenant_parent", "agent_runs", ["tenant_id", "parent_run_id"]
    )
    op.create_index("ix_agent_runs_tenant_created", "agent_runs", ["tenant_id", "created_at"])

    op.create_table(
        "agent_steps",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(100), nullable=False),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("step_key", sa.String(200), nullable=False),
        sa.Column("request_hash", sa.String(128), nullable=False),
        sa.Column("step_type", sa.String(30), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("input", sa.JSON(), nullable=False),
        sa.Column("output", sa.JSON(), nullable=False),
        sa.Column("action_proposal_id", sa.String(36), nullable=True),
        sa.Column("child_run_id", sa.String(36), nullable=True),
        sa.Column("context_assembly_id", sa.String(36), nullable=True),
        sa.Column("tokens", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", "step_key", name="uq_agent_steps_run_key"),
        sa.UniqueConstraint("run_id", "seq", name="uq_agent_steps_run_seq"),
    )
    op.create_index("ix_agent_steps_tenant_run", "agent_steps", ["tenant_id", "run_id"])

    op.create_table(
        "agent_messages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(100), nullable=False),
        sa.Column("root_run_id", sa.String(36), nullable=False),
        sa.Column("from_run_id", sa.String(36), nullable=False),
        sa.Column("to_run_id", sa.String(36), nullable=True),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("body", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_agent_messages_tenant_root", "agent_messages", ["tenant_id", "root_run_id"]
    )
    op.create_index("ix_agent_messages_tenant_to", "agent_messages", ["tenant_id", "to_run_id"])


def downgrade() -> None:
    op.drop_index("ix_agent_messages_tenant_to", table_name="agent_messages")
    op.drop_index("ix_agent_messages_tenant_root", table_name="agent_messages")
    op.drop_table("agent_messages")
    op.drop_index("ix_agent_steps_tenant_run", table_name="agent_steps")
    op.drop_table("agent_steps")
    op.drop_index("ix_agent_runs_tenant_created", table_name="agent_runs")
    op.drop_index("ix_agent_runs_tenant_parent", table_name="agent_runs")
    op.drop_index("ix_agent_runs_tenant_root", table_name="agent_runs")
    op.drop_index("ix_agent_runs_tenant_status", table_name="agent_runs")
    op.drop_table("agent_runs")
    op.drop_index("ix_agents_tenant_status", table_name="agents")
    op.drop_table("agents")
