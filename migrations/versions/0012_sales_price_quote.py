"""sales: котировки цен (Price Engine — история и минимальная цена)

Revision ID: 0012
Revises: 0011
Create Date: 2026-06-03
"""
import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "price_quote",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sku_code", sa.String(length=64), nullable=False),
        sa.Column("counterparty", sa.String(length=255), server_default="", nullable=False),
        sa.Column("price", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        schema="sales",
    )


def downgrade() -> None:
    op.drop_table("price_quote", schema="sales")
