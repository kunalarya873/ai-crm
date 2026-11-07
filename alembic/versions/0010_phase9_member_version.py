"""add optimistic-concurrency version to memberships

Revision ID: 0010_phase9_member_version
Revises: 0009_phase8_proposal_editor
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0010_phase9_member_version"
down_revision: str | None = "0009_phase8_proposal_editor"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("memberships") as batch_op:
        batch_op.add_column(
            sa.Column("version", sa.Integer(), nullable=False, server_default="1")
        )


def downgrade() -> None:
    with op.batch_alter_table("memberships") as batch_op:
        batch_op.drop_column("version")
