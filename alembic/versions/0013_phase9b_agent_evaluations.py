"""add agent coordination evaluation results

Revision ID: 0013_phase9b_agent_evaluations
Revises: 0012_phase9_agents
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0013_phase9b_agent_evaluations"
down_revision: str | None = "0012_phase9_agents"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_eval_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(100), nullable=False),
        sa.Column("scenario_key", sa.String(100), nullable=False),
        sa.Column("strategy", sa.String(30), nullable=False),
        sa.Column("replay_key", sa.String(100), nullable=False),
        sa.Column("task_success", sa.Boolean(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("run_ids", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "tenant_id", "scenario_key", "strategy", "replay_key", name="uq_agent_eval_runs_replay"
        ),
    )
    op.create_index(
        "ix_agent_eval_runs_tenant_scenario", "agent_eval_runs", ["tenant_id", "scenario_key"]
    )
    op.create_index(
        "ix_agent_eval_runs_tenant_created", "agent_eval_runs", ["tenant_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_agent_eval_runs_tenant_created", table_name="agent_eval_runs")
    op.drop_index("ix_agent_eval_runs_tenant_scenario", table_name="agent_eval_runs")
    op.drop_table("agent_eval_runs")
