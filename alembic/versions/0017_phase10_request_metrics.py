"""add per-minute request metric buckets for API SLOs

Revision ID: 0017_phase10_request_metrics
Revises: 0016_phase10_worker_indexes
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0017_phase10_request_metrics"
down_revision: str | None = "0016_phase10_worker_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LATENCY_COLUMNS = (
    "le_25", "le_50", "le_100", "le_250", "le_500", "le_1000", "le_2500", "le_5000", "le_inf",
)


def upgrade() -> None:
    op.create_table(
        "request_metric_buckets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(100), nullable=False),
        sa.Column("bucket_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("route", sa.String(200), nullable=False),
        sa.Column("method", sa.String(10), nullable=False),
        sa.Column("status_class", sa.String(10), nullable=False),
        sa.Column("process_id", sa.String(60), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("latency_sum_ms", sa.Float(), nullable=False),
        *(sa.Column(name, sa.Integer(), nullable=False) for name in LATENCY_COLUMNS),
    )
    op.create_index(
        "ix_request_metric_buckets_tenant_start",
        "request_metric_buckets",
        ["tenant_id", "bucket_start"],
    )


def downgrade() -> None:
    op.drop_index("ix_request_metric_buckets_tenant_start", table_name="request_metric_buckets")
    op.drop_table("request_metric_buckets")
