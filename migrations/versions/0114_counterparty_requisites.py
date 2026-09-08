"""core: counterparty requisites and optimistic revision.

Revision ID: 0114
Revises: 0113
Number reserved through the shared migration registry for CRM-CP-001.
Downgrade discards data stored in these two new columns.
"""
import sqlalchemy as sa
from alembic import op

revision = "0114"
down_revision = "0113"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "counterparty",
        sa.Column("requisites", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
    )
    op.add_column(
        "counterparty",
        sa.Column("revision", sa.Integer(), server_default=sa.text("1"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("counterparty", "revision")
    op.drop_column("counterparty", "requisites")
