"""add legal holds and erasure records

Revision ID: 0018_phase10_lifecycle
Revises: 0017_phase10_request_metrics
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0018_phase10_lifecycle"
down_revision: str | None = "0017_phase10_request_metrics"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "legal_holds",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(100), nullable=False),
        sa.Column("scope", sa.String(20), nullable=False),
        sa.Column("resource_type", sa.String(30), nullable=True),
        sa.Column("record_id", sa.String(36), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("released_by", sa.String(100), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("release_reason", sa.Text(), nullable=True),
    )
    op.create_index("ix_legal_holds_tenant_released", "legal_holds", ["tenant_id", "released_at"])
    op.create_table(
        "erasure_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(100), nullable=False),
        sa.Column("resource_type", sa.String(30), nullable=False),
        sa.Column("record_id", sa.String(36), nullable=False),
        sa.Column("erased_by", sa.String(100), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("erased_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "tenant_id", "resource_type", "record_id", name="uq_erasure_records_record"
        ),
    )


def downgrade() -> None:
    op.drop_table("erasure_records")
    op.drop_index("ix_legal_holds_tenant_released", table_name="legal_holds")
    op.drop_table("legal_holds")
