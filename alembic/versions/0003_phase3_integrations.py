"""add provider-neutral integration foundations

Revision ID: 0003_phase3_integrations
Revises: 0002_phase2_core_domain
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003_phase3_integrations"
down_revision: str | None = "0002_phase2_core_domain"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "integration_connections",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=100), nullable=False),
        sa.Column("provider_key", sa.String(length=50), nullable=False),
        sa.Column("external_account_id", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("secret_ref", sa.String(length=500), nullable=False),
        sa.Column("configuration", sa.JSON(), nullable=False),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider_key",
            "external_account_id",
            name="uq_integration_provider_account",
        ),
    )
    op.create_index(
        "ix_integration_connections_tenant_status",
        "integration_connections",
        ["tenant_id", "status"],
    )

    op.create_table(
        "integration_record_links",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("connection_id", sa.String(length=36), nullable=False),
        sa.Column("resource_type", sa.String(length=50), nullable=False),
        sa.Column("provider_record_id", sa.String(length=200), nullable=False),
        sa.Column("canonical_type", sa.String(length=50), nullable=False),
        sa.Column("canonical_id", sa.String(length=100), nullable=False),
        sa.Column("source_url", sa.String(length=1000), nullable=True),
        sa.Column("provider_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "connection_id",
            "resource_type",
            "provider_record_id",
            name="uq_integration_record_link",
        ),
    )
    op.create_index(
        "ix_integration_links_connection_resource",
        "integration_record_links",
        ["connection_id", "resource_type"],
    )

    op.create_table(
        "integration_sync_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("connection_id", sa.String(length=36), nullable=False),
        sa.Column("resource_type", sa.String(length=50), nullable=False),
        sa.Column("mode", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("cursor", sa.String(length=500), nullable=True),
        sa.Column("lease_owner", sa.String(length=100), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("records_processed", sa.Integer(), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_code", sa.String(length=100), nullable=True),
        sa.Column("failure_detail", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_integration_sync_connection_created",
        "integration_sync_runs",
        ["connection_id", "created_at"],
    )
    op.create_index(
        "ix_integration_sync_status_lease",
        "integration_sync_runs",
        ["status", "lease_expires_at"],
    )

    op.create_table(
        "webhook_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("connection_id", sa.String(length=36), nullable=False),
        sa.Column("provider_event_id", sa.String(length=200), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("payload_hash", sa.String(length=128), nullable=False),
        sa.Column("provider_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("signature_valid", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_code", sa.String(length=100), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "connection_id",
            "provider_event_id",
            name="uq_webhook_connection_event",
        ),
    )
    op.create_index(
        "ix_webhook_connection_received",
        "webhook_events",
        ["connection_id", "received_at"],
    )

    op.create_table(
        "external_writes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("connection_id", sa.String(length=36), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("operation", sa.String(length=100), nullable=False),
        sa.Column("request_hash", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("provider_request_id", sa.String(length=200), nullable=True),
        sa.Column("response_metadata", sa.JSON(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "connection_id",
            "idempotency_key",
            name="uq_external_write_idempotency",
        ),
    )
    op.create_index(
        "ix_external_writes_connection_created",
        "external_writes",
        ["connection_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_external_writes_connection_created", table_name="external_writes")
    op.drop_table("external_writes")
    op.drop_index("ix_webhook_connection_received", table_name="webhook_events")
    op.drop_table("webhook_events")
    op.drop_index("ix_integration_sync_status_lease", table_name="integration_sync_runs")
    op.drop_index("ix_integration_sync_connection_created", table_name="integration_sync_runs")
    op.drop_table("integration_sync_runs")
    op.drop_index("ix_integration_links_connection_resource", table_name="integration_record_links")
    op.drop_table("integration_record_links")
    op.drop_index(
        "ix_integration_connections_tenant_status",
        table_name="integration_connections",
    )
    op.drop_table("integration_connections")
