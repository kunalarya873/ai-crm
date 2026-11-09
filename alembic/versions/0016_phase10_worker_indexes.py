"""add indexes the worker uses to find tenants with ready work

Revision ID: 0016_phase10_worker_indexes
Revises: 0015_phase10_reason_text
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0016_phase10_worker_indexes"
down_revision: str | None = "0015_phase10_reason_text"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_durable_jobs_status_run_at", "durable_jobs", ["status", "run_at"])
    op.create_index("ix_agent_runs_status_deadline", "agent_runs", ["status", "deadline_at"])


def downgrade() -> None:
    op.drop_index("ix_agent_runs_status_deadline", table_name="agent_runs")
    op.drop_index("ix_durable_jobs_status_run_at", table_name="durable_jobs")
