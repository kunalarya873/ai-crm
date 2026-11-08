"""widen workflow_transitions.reason to match the model and the 5000-character API limit

Revision ID: 0015_phase10_reason_text
Revises: 0014_phase10_feature_flags
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0015_phase10_reason_text"
down_revision: str | None = "0014_phase10_feature_flags"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("workflow_transitions") as batch:
        batch.alter_column(
            "reason", existing_type=sa.String(500), type_=sa.Text(), existing_nullable=True
        )


def downgrade() -> None:
    # Reasons longer than 500 characters are truncated first: databases that enforce VARCHAR
    # length would otherwise abort the rollback.
    op.execute(
        "UPDATE workflow_transitions SET reason = substr(reason, 1, 500) "
        "WHERE length(reason) > 500"
    )
    with op.batch_alter_table("workflow_transitions") as batch:
        batch.alter_column(
            "reason", existing_type=sa.Text(), type_=sa.String(500), existing_nullable=True
        )
