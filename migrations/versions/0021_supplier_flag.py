"""procurement: флаг страны поставщика на карточке закупки

Revision ID: 0021
Revises: 0020
Create Date: 2026-06-05
"""
import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "purchase_request",
        sa.Column("flag", sa.String(length=8), server_default="", nullable=False),
        schema="procurement",
    )


def downgrade() -> None:
    op.drop_column("purchase_request", "flag", schema="procurement")
