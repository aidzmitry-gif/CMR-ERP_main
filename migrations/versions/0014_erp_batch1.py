"""erp: модули Закупки / Производство / Склад

Revision ID: 0014
Revises: 0013
Create Date: 2026-06-03
"""
import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS procurement")
    op.create_table(
        "purchase_request",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("supplier", sa.String(length=255), nullable=False),
        sa.Column("item", sa.String(length=255), nullable=False),
        sa.Column("qty", sa.Integer(), server_default="1", nullable=False),
        sa.Column("status", sa.String(length=32), server_default="new", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        schema="procurement",
    )

    op.execute("CREATE SCHEMA IF NOT EXISTS production")
    op.create_table(
        "production_order",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product", sa.String(length=255), nullable=False),
        sa.Column("qty", sa.Integer(), server_default="1", nullable=False),
        sa.Column("status", sa.String(length=32), server_default="planned", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        schema="production",
    )

    op.execute("CREATE SCHEMA IF NOT EXISTS wms")
    op.create_table(
        "stock_movement",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sku_code", sa.String(length=64), nullable=False),
        sa.Column("warehouse", sa.String(length=128), server_default="Главный", nullable=False),
        sa.Column("kind", sa.String(length=8), server_default="in", nullable=False),
        sa.Column("qty", sa.Numeric(precision=14, scale=2), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        schema="wms",
    )


def downgrade() -> None:
    op.drop_table("stock_movement", schema="wms")
    op.execute("DROP SCHEMA IF EXISTS wms")
    op.drop_table("production_order", schema="production")
    op.execute("DROP SCHEMA IF EXISTS production")
    op.drop_table("purchase_request", schema="procurement")
    op.execute("DROP SCHEMA IF EXISTS procurement")
