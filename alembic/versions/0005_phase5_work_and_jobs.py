"""add durable work items, jobs, reminders, and workflows

Revision ID: 0005_phase5_work_and_jobs
Revises: 0004_phase4_knowledge
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005_phase5_work_and_jobs"
down_revision: str | None = "0004_phase4_knowledge"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "work_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=100), nullable=False),
        sa.Column("item_type", sa.String(length=30), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.String(length=100), nullable=True),
        sa.Column("assignee_id", sa.String(length=100), nullable=True),
        sa.Column("team_key", sa.String(length=100), nullable=True),
        sa.Column("contact_id", sa.String(length=36), nullable=True),
        sa.Column("opportunity_id", sa.String(length=36), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("depends_on_ids", sa.JSON(), nullable=False),
        sa.Column("completion_evidence", sa.Text(), nullable=True),
        sa.Column("blocked_reason", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=100), nullable=True),
        sa.Column("created_by", sa.String(length=100), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_work_items_tenant_status_due",
        "work_items",
        ["tenant_id", "status", "due_at"],
    )
    op.create_index(
        "ix_work_items_tenant_assignee",
        "work_items",
        ["tenant_id", "assignee_id", "status"],
    )
    op.create_index(
        "ix_work_items_tenant_owner",
        "work_items",
        ["tenant_id", "owner_id", "status"],
    )

    op.create_table(
        "work_item_transitions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=100), nullable=False),
        sa.Column("work_item_id", sa.String(length=36), nullable=False),
        sa.Column("from_status", sa.String(length=30), nullable=False),
        sa.Column("to_status", sa.String(length=30), nullable=False),
        sa.Column("actor_id", sa.String(length=100), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_work_item_transitions_item_created",
        "work_item_transitions",
        ["work_item_id", "created_at"],
    )
    op.create_index(
        "ix_work_item_transitions_tenant_created",
        "work_item_transitions",
        ["tenant_id", "created_at"],
    )

    op.create_table(
        "reminder_deliveries",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=100), nullable=False),
        sa.Column("work_item_id", sa.String(length=36), nullable=False),
        sa.Column("reminder_kind", sa.String(length=50), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "work_item_id",
            "reminder_kind",
            "scheduled_for",
            name="uq_reminder_work_item_schedule",
        ),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_reminder_idempotency"),
    )
    op.create_index(
        "ix_reminders_tenant_status_schedule",
        "reminder_deliveries",
        ["tenant_id", "status", "scheduled_for"],
    )

    op.create_table(
        "durable_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=100), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("request_hash", sa.String(length=128), nullable=False),
        sa.Column("job_type", sa.String(length=100), nullable=False),
        sa.Column("queue", sa.String(length=100), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("backoff_seconds", sa.Integer(), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_owner", sa.String(length=100), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("timeout_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_detail", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_durable_job_idempotency"),
    )
    op.create_index(
        "ix_durable_jobs_tenant_queue_ready",
        "durable_jobs",
        ["tenant_id", "queue", "status", "run_at"],
    )
    op.create_index("ix_durable_jobs_tenant_status", "durable_jobs", ["tenant_id", "status"])
    op.create_index("ix_durable_jobs_lease", "durable_jobs", ["status", "lease_expires_at"])

    op.create_table(
        "workflow_instances",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=100), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("workflow_key", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("owner_id", sa.String(length=100), nullable=True),
        sa.Column("current_step", sa.Integer(), nullable=False),
        sa.Column("steps", sa.JSON(), nullable=False),
        sa.Column("input_refs", sa.JSON(), nullable=False),
        sa.Column("outputs", sa.JSON(), nullable=False),
        sa.Column("waiting_for", sa.String(length=100), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_detail", sa.String(length=500), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_workflow_idempotency"),
    )
    op.create_index("ix_workflows_tenant_status", "workflow_instances", ["tenant_id", "status"])
    op.create_index(
        "ix_workflows_tenant_owner",
        "workflow_instances",
        ["tenant_id", "owner_id", "status"],
    )

    op.create_table(
        "workflow_transitions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=100), nullable=False),
        sa.Column("workflow_id", sa.String(length=36), nullable=False),
        sa.Column("from_status", sa.String(length=30), nullable=False),
        sa.Column("to_status", sa.String(length=30), nullable=False),
        sa.Column("from_step", sa.Integer(), nullable=False),
        sa.Column("to_step", sa.Integer(), nullable=False),
        sa.Column("actor_id", sa.String(length=100), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_workflow_transitions_instance_created",
        "workflow_transitions",
        ["workflow_id", "created_at"],
    )
    op.create_index(
        "ix_workflow_transitions_tenant_created",
        "workflow_transitions",
        ["tenant_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_workflow_transitions_tenant_created", table_name="workflow_transitions")
    op.drop_index("ix_workflow_transitions_instance_created", table_name="workflow_transitions")
    op.drop_table("workflow_transitions")
    op.drop_index("ix_workflows_tenant_owner", table_name="workflow_instances")
    op.drop_index("ix_workflows_tenant_status", table_name="workflow_instances")
    op.drop_table("workflow_instances")
    op.drop_index("ix_durable_jobs_lease", table_name="durable_jobs")
    op.drop_index("ix_durable_jobs_tenant_status", table_name="durable_jobs")
    op.drop_index("ix_durable_jobs_tenant_queue_ready", table_name="durable_jobs")
    op.drop_table("durable_jobs")
    op.drop_index("ix_reminders_tenant_status_schedule", table_name="reminder_deliveries")
    op.drop_table("reminder_deliveries")
    op.drop_index("ix_work_item_transitions_tenant_created", table_name="work_item_transitions")
    op.drop_index("ix_work_item_transitions_item_created", table_name="work_item_transitions")
    op.drop_table("work_item_transitions")
    op.drop_index("ix_work_items_tenant_owner", table_name="work_items")
    op.drop_index("ix_work_items_tenant_assignee", table_name="work_items")
    op.drop_index("ix_work_items_tenant_status_due", table_name="work_items")
    op.drop_table("work_items")
