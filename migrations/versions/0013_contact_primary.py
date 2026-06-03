"""core: признак основного контакта (is_primary)

Revision ID: 0013
Revises: 0012
Create Date: 2026-06-03
"""
import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "contact",
        sa.Column("is_primary", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("contact", "is_primary")
