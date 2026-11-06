"""add typed action proposals and executions

Revision ID: 0007_phase7_actions
Revises: 0006_phase6_ai_gateway
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007_phase7_actions"
down_revision: str | None = "0006_phase6_ai_gateway"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "action_proposals",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=100), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("request_hash", sa.String(length=128), nullable=False),
        sa.Column("action_type", sa.String(length=100), nullable=False),
        sa.Column("action_version", sa.String(length=50), nullable=False),
        sa.Column("required_permission", sa.String(length=100), nullable=False),
        sa.Column("risk_level", sa.String(length=30), nullable=False),
        sa.Column("requires_approval", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("affected_resources", sa.JSON(), nullable=False),
        sa.Column("intended_changes", sa.JSON(), nullable=False),
        sa.Column("expected_side_effects", sa.JSON(), nullable=False),
        sa.Column("source_ai_run_id", sa.String(length=36), nullable=True),
        sa.Column("requested_by", sa.String(length=100), nullable=False),
        sa.Column("approved_by", sa.String(length=100), nullable=True),
        sa.Column("rejected_by", sa.String(length=100), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("last_error_code", sa.String(length=100), nullable=True),
        sa.Column("last_error_detail", sa.String(length=500), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_action_proposals_tenant_idempotency",
        ),
    )
    op.create_index(
        "ix_action_proposals_tenant_status",
        "action_proposals",
        ["tenant_id", "status"],
    )
    op.create_index(
        "ix_action_proposals_tenant_expires",
        "action_proposals",
        ["tenant_id", "status", "expires_at"],
    )
    op.create_index(
        "ix_action_proposals_tenant_created",
        "action_proposals",
        ["tenant_id", "created_at"],
    )

    op.create_table(
        "action_executions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=100), nullable=False),
        sa.Column("action_proposal_id", sa.String(length=36), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("action_type", sa.String(length=100), nullable=False),
        sa.Column("request_hash", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("provider_request_id", sa.String(length=200), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_detail", sa.String(length=500), nullable=True),
        sa.Column("operator_note", sa.Text(), nullable=True),
        sa.Column("uncertain_outcome", sa.Boolean(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "action_proposal_id",
            name="uq_action_execution_proposal",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_action_execution_tenant_idempotency",
        ),
    )
    op.create_index(
        "ix_action_executions_tenant_status",
        "action_executions",
        ["tenant_id", "status"],
    )
    op.create_index(
        "ix_action_executions_tenant_created",
        "action_executions",
        ["tenant_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_action_executions_tenant_created", table_name="action_executions")
    op.drop_index("ix_action_executions_tenant_status", table_name="action_executions")
    op.drop_table("action_executions")
    op.drop_index("ix_action_proposals_tenant_created", table_name="action_proposals")
    op.drop_index("ix_action_proposals_tenant_expires", table_name="action_proposals")
    op.drop_index("ix_action_proposals_tenant_status", table_name="action_proposals")
    op.drop_table("action_proposals")
