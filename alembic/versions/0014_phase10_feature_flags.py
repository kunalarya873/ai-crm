"""add tenant feature flags (kill switches)

Revision ID: 0014_phase10_feature_flags
Revises: 0013_phase9b_agent_evaluations
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0014_phase10_feature_flags"
down_revision: str | None = "0013_phase9b_agent_evaluations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tenant_feature_flags",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(100), nullable=False),
        sa.Column("flag_key", sa.String(50), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.String(500), nullable=True),
        sa.Column("updated_by", sa.String(100), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "flag_key", name="uq_tenant_feature_flags_key"),
    )


def downgrade() -> None:
    op.drop_table("tenant_feature_flags")
