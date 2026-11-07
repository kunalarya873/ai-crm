"""add trace ids to operational events and durable jobs

Revision ID: 0011_phase8_trace_context
Revises: 0010_phase9_member_version
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0011_phase8_trace_context"
down_revision: str | None = "0010_phase9_member_version"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("operational_events") as batch_op:
        batch_op.add_column(sa.Column("trace_id", sa.String(length=32), nullable=True))
        batch_op.create_index("ix_operational_events_trace", ["tenant_id", "trace_id"])
    with op.batch_alter_table("durable_jobs") as batch_op:
        batch_op.add_column(sa.Column("trace_id", sa.String(length=32), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("durable_jobs") as batch_op:
        batch_op.drop_column("trace_id")
    with op.batch_alter_table("operational_events") as batch_op:
        batch_op.drop_index("ix_operational_events_trace")
        batch_op.drop_column("trace_id")
