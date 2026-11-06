"""add AI prompt, run, and feedback records

Revision ID: 0006_phase6_ai_gateway
Revises: 0005_phase5_work_and_jobs
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006_phase6_ai_gateway"
down_revision: str | None = "0005_phase5_work_and_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_prompt_versions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("use_case", sa.String(length=100), nullable=False),
        sa.Column("version", sa.String(length=50), nullable=False),
        sa.Column("catalog_version", sa.String(length=50), nullable=False),
        sa.Column("template", sa.Text(), nullable=False),
        sa.Column("template_hash", sa.String(length=128), nullable=False),
        sa.Column("output_schema_version", sa.String(length=50), nullable=False),
        sa.Column("policy_version", sa.String(length=50), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("use_case", "version", name="uq_ai_prompt_use_case_version"),
    )
    op.create_index(
        "ix_ai_prompts_use_case_active",
        "ai_prompt_versions",
        ["use_case", "active"],
    )

    op.create_table(
        "ai_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=100), nullable=False),
        sa.Column("actor_id", sa.String(length=100), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("request_hash", sa.String(length=128), nullable=False),
        sa.Column("use_case", sa.String(length=100), nullable=False),
        sa.Column("provider_key", sa.String(length=100), nullable=False),
        sa.Column("model_key", sa.String(length=100), nullable=False),
        sa.Column("config_version", sa.String(length=100), nullable=False),
        sa.Column("prompt_version", sa.String(length=50), nullable=False),
        sa.Column("prompt_hash", sa.String(length=128), nullable=False),
        sa.Column("feature_flag", sa.String(length=100), nullable=False),
        sa.Column("context_assembly_id", sa.String(length=36), nullable=True),
        sa.Column("context_refs", sa.JSON(), nullable=False),
        sa.Column("request", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("validation_status", sa.String(length=30), nullable=False),
        sa.Column("output", sa.JSON(), nullable=False),
        sa.Column("output_text", sa.Text(), nullable=True),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("uncertainty", sa.JSON(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("provider_attempts", sa.Integer(), nullable=False),
        sa.Column("estimated_cost_micros", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_detail", sa.String(length=500), nullable=True),
        sa.Column("fallback_reason", sa.String(length=500), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_ai_runs_tenant_idempotency"),
    )
    op.create_index("ix_ai_runs_tenant_created", "ai_runs", ["tenant_id", "created_at"])
    op.create_index(
        "ix_ai_runs_tenant_use_case_status",
        "ai_runs",
        ["tenant_id", "use_case", "status"],
    )
    op.create_index(
        "ix_ai_runs_provider_model",
        "ai_runs",
        ["provider_key", "model_key", "created_at"],
    )

    op.create_table(
        "ai_feedback",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=100), nullable=False),
        sa.Column("ai_run_id", sa.String(length=36), nullable=False),
        sa.Column("actor_id", sa.String(length=100), nullable=False),
        sa.Column("feedback_type", sa.String(length=30), nullable=False),
        sa.Column("edited_output", sa.JSON(), nullable=True),
        sa.Column("correction_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_feedback_run_created", "ai_feedback", ["ai_run_id", "created_at"])
    op.create_index("ix_ai_feedback_tenant_created", "ai_feedback", ["tenant_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_ai_feedback_tenant_created", table_name="ai_feedback")
    op.drop_index("ix_ai_feedback_run_created", table_name="ai_feedback")
    op.drop_table("ai_feedback")
    op.drop_index("ix_ai_runs_provider_model", table_name="ai_runs")
    op.drop_index("ix_ai_runs_tenant_use_case_status", table_name="ai_runs")
    op.drop_index("ix_ai_runs_tenant_created", table_name="ai_runs")
    op.drop_table("ai_runs")
    op.drop_index("ix_ai_prompts_use_case_active", table_name="ai_prompt_versions")
    op.drop_table("ai_prompt_versions")
