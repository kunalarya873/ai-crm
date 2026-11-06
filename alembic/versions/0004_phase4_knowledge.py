"""add permission-aware knowledge and context foundations

Revision ID: 0004_phase4_knowledge
Revises: 0003_phase3_integrations
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004_phase4_knowledge"
down_revision: str | None = "0003_phase3_integrations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_sources",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=100), nullable=False),
        sa.Column("source_type", sa.String(length=50), nullable=False),
        sa.Column("source_record_id", sa.String(length=200), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source_url", sa.String(length=1000), nullable=True),
        sa.Column("owner_id", sa.String(length=100), nullable=True),
        sa.Column("visibility", sa.String(length=30), nullable=False),
        sa.Column("allowed_user_ids", sa.JSON(), nullable=False),
        sa.Column("customer_id", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("searchable", sa.Boolean(), nullable=False),
        sa.Column("ai_allowed", sa.Boolean(), nullable=False),
        sa.Column("sensitivity", sa.String(length=30), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fresh_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "source_type",
            "source_record_id",
            name="uq_knowledge_source_record",
        ),
    )
    op.create_index(
        "ix_knowledge_sources_tenant_status",
        "knowledge_sources",
        ["tenant_id", "status"],
    )
    op.create_index(
        "ix_knowledge_sources_tenant_type",
        "knowledge_sources",
        ["tenant_id", "source_type"],
    )
    op.create_index(
        "ix_knowledge_sources_tenant_updated",
        "knowledge_sources",
        ["tenant_id", "updated_at"],
    )

    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=100), nullable=False),
        sa.Column("source_id", sa.String(length=36), nullable=False),
        sa.Column("source_version", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=128), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_id",
            "source_version",
            "chunk_index",
            name="uq_knowledge_chunk_version",
        ),
    )
    op.create_index(
        "ix_knowledge_chunks_source_status",
        "knowledge_chunks",
        ["source_id", "status"],
    )
    op.create_index(
        "ix_knowledge_chunks_tenant_status",
        "knowledge_chunks",
        ["tenant_id", "status"],
    )

    op.create_table(
        "knowledge_index_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=100), nullable=False),
        sa.Column("source_id", sa.String(length=36), nullable=False),
        sa.Column("source_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("lease_owner", sa.String(length=100), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("indexed_chunks", sa.Integer(), nullable=False),
        sa.Column("failure_code", sa.String(length=100), nullable=True),
        sa.Column("failure_detail", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_id",
            "source_version",
            name="uq_knowledge_index_source_version",
        ),
    )
    op.create_index(
        "ix_knowledge_index_jobs_tenant_status",
        "knowledge_index_jobs",
        ["tenant_id", "status"],
    )
    op.create_index(
        "ix_knowledge_index_jobs_lease",
        "knowledge_index_jobs",
        ["status", "lease_expires_at"],
    )

    op.create_table(
        "knowledge_context_assemblies",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=100), nullable=False),
        sa.Column("actor_id", sa.String(length=100), nullable=False),
        sa.Column("query", sa.String(length=500), nullable=False),
        sa.Column("request_scope", sa.JSON(), nullable=False),
        sa.Column("item_ids", sa.JSON(), nullable=False),
        sa.Column("citations", sa.JSON(), nullable=False),
        sa.Column("used_chars", sa.Integer(), nullable=False),
        sa.Column("max_items", sa.Integer(), nullable=False),
        sa.Column("max_chars", sa.Integer(), nullable=False),
        sa.Column("truncated", sa.Boolean(), nullable=False),
        sa.Column("insufficient_evidence", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_knowledge_context_tenant_created",
        "knowledge_context_assemblies",
        ["tenant_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_knowledge_context_tenant_created", table_name="knowledge_context_assemblies")
    op.drop_table("knowledge_context_assemblies")
    op.drop_index("ix_knowledge_index_jobs_lease", table_name="knowledge_index_jobs")
    op.drop_index("ix_knowledge_index_jobs_tenant_status", table_name="knowledge_index_jobs")
    op.drop_table("knowledge_index_jobs")
    op.drop_index("ix_knowledge_chunks_tenant_status", table_name="knowledge_chunks")
    op.drop_index("ix_knowledge_chunks_source_status", table_name="knowledge_chunks")
    op.drop_table("knowledge_chunks")
    op.drop_index("ix_knowledge_sources_tenant_updated", table_name="knowledge_sources")
    op.drop_index("ix_knowledge_sources_tenant_type", table_name="knowledge_sources")
    op.drop_index("ix_knowledge_sources_tenant_status", table_name="knowledge_sources")
    op.drop_table("knowledge_sources")
