"""record last editor on action proposals

Revision ID: 0009_phase8_proposal_editor
Revises: 0008_phase8_observability
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009_phase8_proposal_editor"
down_revision: str | None = "0008_phase8_observability"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("action_proposals") as batch_op:
        batch_op.add_column(sa.Column("last_edited_by", sa.String(length=100), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("action_proposals") as batch_op:
        batch_op.drop_column("last_edited_by")
