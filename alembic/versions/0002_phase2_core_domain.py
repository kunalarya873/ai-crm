"""add Phase 2 CRM core domain

Revision ID: 0002_phase2_core_domain
Revises: 0001_phase1_foundation
"""
from collections.abc import Sequence
from uuid import NAMESPACE_URL, uuid5

import sqlalchemy as sa

from alembic import op

revision: str = "0002_phase2_core_domain"
down_revision: str | None = "0001_phase1_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def normalize_name(value: str) -> str:
    return " ".join(value.casefold().split())


def upgrade() -> None:
    op.create_table(
        "companies",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("normalized_name", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("owner_id", sa.String(length=100), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "normalized_name", name="uq_companies_tenant_name"),
    )
    op.create_index("ix_companies_tenant_status", "companies", ["tenant_id", "status"])
    op.create_index("ix_companies_tenant_owner", "companies", ["tenant_id", "owner_id"])

    op.create_table(
        "opportunities",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=True),
        sa.Column("contact_id", sa.String(length=36), nullable=True),
        sa.Column("stage", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("priority", sa.String(length=30), nullable=False),
        sa.Column("owner_id", sa.String(length=100), nullable=True),
        sa.Column("next_step", sa.String(length=500), nullable=True),
        sa.Column("expected_close_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("win_loss_reason", sa.String(length=500), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_opportunities_tenant_stage", "opportunities", ["tenant_id", "stage"])
    op.create_index("ix_opportunities_tenant_owner", "opportunities", ["tenant_id", "owner_id"])
    op.create_index("ix_opportunities_tenant_company", "opportunities", ["tenant_id", "company_id"])

    op.create_table(
        "activities",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=100), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("subject", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("event_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("contact_id", sa.String(length=36), nullable=True),
        sa.Column("company_id", sa.String(length=36), nullable=True),
        sa.Column("opportunity_id", sa.String(length=36), nullable=True),
        sa.Column("actor_id", sa.String(length=100), nullable=True),
        sa.Column("source_system", sa.String(length=100), nullable=True),
        sa.Column("source_record_id", sa.String(length=200), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "source_system",
            "source_record_id",
            name="uq_activities_tenant_source_record",
        ),
    )
    op.create_index(
        "ix_activities_tenant_event",
        "activities",
        ["tenant_id", "event_at", "ingested_at"],
    )
    op.create_index("ix_activities_tenant_contact", "activities", ["tenant_id", "contact_id"])
    op.create_index(
        "ix_activities_tenant_opportunity",
        "activities",
        ["tenant_id", "opportunity_id"],
    )

    with op.batch_alter_table("contacts") as batch_op:
        batch_op.add_column(sa.Column("company_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("version", sa.Integer(), server_default="1", nullable=False))

    with op.batch_alter_table("tasks") as batch_op:
        batch_op.add_column(
            sa.Column("priority", sa.String(length=30), server_default="normal", nullable=False)
        )
        batch_op.add_column(sa.Column("opportunity_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("completion_evidence", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("source", sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("version", sa.Integer(), server_default="1", nullable=False))

    op.create_index("ix_contacts_tenant_company", "contacts", ["tenant_id", "company_id"])
    op.create_index("ix_tasks_tenant_opportunity", "tasks", ["tenant_id", "opportunity_id"])

    connection = op.get_bind()
    legacy_companies = connection.execute(
        sa.text(
            "SELECT DISTINCT tenant_id, company_name "
            "FROM contacts WHERE company_name IS NOT NULL AND trim(company_name) <> ''"
        )
    ).mappings()
    seen_companies: set[tuple[str, str]] = set()
    for row in legacy_companies:
        tenant_id = str(row["tenant_id"])
        company_name = str(row["company_name"]).strip()
        normalized = normalize_name(company_name)
        company_key = (tenant_id, normalized)
        if company_key in seen_companies:
            continue
        seen_companies.add(company_key)
        company_id = str(uuid5(NAMESPACE_URL, f"{tenant_id}:{normalized}"))
        connection.execute(
            sa.text(
                "INSERT INTO companies "
                "(id, tenant_id, name, normalized_name, status, version, created_at, updated_at) "
                "VALUES (:id, :tenant_id, :name, :normalized_name, 'prospect', 1, "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {
                "id": company_id,
                "tenant_id": tenant_id,
                "name": company_name,
                "normalized_name": normalized,
            },
        )
        connection.execute(
            sa.text(
                "UPDATE contacts SET company_id = :company_id "
                "WHERE tenant_id = :tenant_id AND lower(trim(company_name)) = :normalized_name"
            ),
            {
                "company_id": company_id,
                "tenant_id": tenant_id,
                "normalized_name": normalized,
            },
        )


def downgrade() -> None:
    op.drop_index("ix_tasks_tenant_opportunity", table_name="tasks")
    with op.batch_alter_table("tasks") as batch_op:
        batch_op.drop_column("version")
        batch_op.drop_column("archived_at")
        batch_op.drop_column("source")
        batch_op.drop_column("completion_evidence")
        batch_op.drop_column("completed_at")
        batch_op.drop_column("opportunity_id")
        batch_op.drop_column("priority")

    op.drop_index("ix_contacts_tenant_company", table_name="contacts")
    with op.batch_alter_table("contacts") as batch_op:
        batch_op.drop_column("version")
        batch_op.drop_column("archived_at")
        batch_op.drop_column("company_id")

    op.drop_index("ix_activities_tenant_opportunity", table_name="activities")
    op.drop_index("ix_activities_tenant_contact", table_name="activities")
    op.drop_index("ix_activities_tenant_event", table_name="activities")
    op.drop_table("activities")
    op.drop_index("ix_opportunities_tenant_company", table_name="opportunities")
    op.drop_index("ix_opportunities_tenant_owner", table_name="opportunities")
    op.drop_index("ix_opportunities_tenant_stage", table_name="opportunities")
    op.drop_table("opportunities")
    op.drop_index("ix_companies_tenant_owner", table_name="companies")
    op.drop_index("ix_companies_tenant_status", table_name="companies")
    op.drop_table("companies")
