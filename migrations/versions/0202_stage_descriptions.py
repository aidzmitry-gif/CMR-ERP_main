"""Shared plain-text instructions for existing sales stages."""

import sqlalchemy as sa
from alembic import op

revision = "0202"
down_revision = "0201"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "stage", sa.Column("description", sa.Text(), nullable=False, server_default=""),
        schema="sales",
    )


def downgrade() -> None:
    if op.get_bind().execute(sa.text(
        "SELECT EXISTS (SELECT 1 FROM sales.stage WHERE description <> '')"
    )).scalar_one():
        raise RuntimeError("Stage descriptions must be preserved before downgrading 0202")
    op.drop_column("stage", "description", schema="sales")
