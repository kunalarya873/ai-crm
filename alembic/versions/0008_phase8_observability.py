"""add operational telemetry, metrics, and alerts

Revision ID: 0008_phase8_observability
Revises: 0007_phase7_actions
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008_phase8_observability"
down_revision: str | None = "0007_phase7_actions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "operational_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=100), nullable=False),
        sa.Column("actor_id", sa.String(length=100), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("event_version", sa.String(length=30), nullable=False),
        sa.Column("operation", sa.String(length=100), nullable=False),
        sa.Column("resource_type", sa.String(length=100), nullable=False),
        sa.Column("resource_id", sa.String(length=100), nullable=False),
        sa.Column("outcome", sa.String(length=30), nullable=False),
        sa.Column("correlation_id", sa.String(length=100), nullable=False),
        sa.Column("dedup_key", sa.String(length=300), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "event_type",
            "dedup_key",
            name="uq_operational_events_dedup",
        ),
    )
    op.create_index(
        "ix_operational_events_tenant_created",
        "operational_events",
        ["tenant_id", "created_at"],
    )
    op.create_index(
        "ix_operational_events_tenant_type",
        "operational_events",
        ["tenant_id", "event_type", "created_at"],
    )
    op.create_index("ix_operational_events_correlation", "operational_events", ["correlation_id"])

    op.create_table(
        "metric_observations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=100), nullable=False),
        sa.Column("metric_key", sa.String(length=100), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(length=30), nullable=False),
        sa.Column("quality", sa.String(length=30), nullable=False),
        sa.Column("dimensions", sa.JSON(), nullable=False),
        sa.Column("source_event_ids", sa.JSON(), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_metric_observations_tenant_key_window",
        "metric_observations",
        ["tenant_id", "metric_key", "window_end"],
    )
    op.create_index(
        "ix_metric_observations_tenant_created",
        "metric_observations",
        ["tenant_id", "created_at"],
    )

    op.create_table(
        "operational_alerts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=100), nullable=False),
        sa.Column("alert_type", sa.String(length=30), nullable=False),
        sa.Column("rule_key", sa.String(length=100), nullable=False),
        sa.Column("rule_version", sa.String(length=30), nullable=False),
        sa.Column("dedup_key", sa.String(length=300), nullable=False),
        sa.Column("severity", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("related_type", sa.String(length=100), nullable=True),
        sa.Column("related_id", sa.String(length=100), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("work_item_id", sa.String(length=36), nullable=True),
        sa.Column("acknowledged_by", sa.String(length=100), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.String(length=100), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "dedup_key", name="uq_operational_alerts_dedup"),
    )
    op.create_index(
        "ix_operational_alerts_tenant_status",
        "operational_alerts",
        ["tenant_id", "status"],
    )
    op.create_index(
        "ix_operational_alerts_tenant_created",
        "operational_alerts",
        ["tenant_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_operational_alerts_tenant_created", table_name="operational_alerts")
    op.drop_index("ix_operational_alerts_tenant_status", table_name="operational_alerts")
    op.drop_table("operational_alerts")
    op.drop_index("ix_metric_observations_tenant_created", table_name="metric_observations")
    op.drop_index("ix_metric_observations_tenant_key_window", table_name="metric_observations")
    op.drop_table("metric_observations")
    op.drop_index("ix_operational_events_correlation", table_name="operational_events")
    op.drop_index("ix_operational_events_tenant_type", table_name="operational_events")
    op.drop_index("ix_operational_events_tenant_created", table_name="operational_events")
    op.drop_table("operational_events")
