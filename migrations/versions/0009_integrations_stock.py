"""integrations: остатки/цены из 1С

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-02
"""
import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS integrations")
    op.create_table(
        "stock_item",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sku_code", sa.String(length=64), nullable=False),
        sa.Column("warehouse", sa.String(length=128), server_default="Главный", nullable=False),
        sa.Column("qty_available", sa.Numeric(precision=14, scale=2), server_default="0", nullable=False),
        sa.Column("qty_reserved", sa.Numeric(precision=14, scale=2), server_default="0", nullable=False),
        sa.Column("qty_forecast", sa.Numeric(precision=14, scale=2), server_default="0", nullable=False),
        sa.Column("price", sa.Numeric(precision=14, scale=2), server_default="0", nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        schema="integrations",
    )


def downgrade() -> None:
    op.drop_table("stock_item", schema="integrations")
    op.execute("DROP SCHEMA IF EXISTS integrations")
