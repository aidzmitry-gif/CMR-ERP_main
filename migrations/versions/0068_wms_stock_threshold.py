"""wms: пороги дефицита (low-stock) — stock_threshold

``wms.stock_threshold`` — минимум и рекомендуемый дозаказ по (SKU, склад). Дефицит
считается на ЧТЕНИЕ против зеркала 1С (свободный остаток); WMS в 1С не пишет.

Revision ID: 0068
Revises: 0067
Create Date: 2026-06-28

Примечание: номер взят атомарно через scripts/next_migration.py (полоса «Склад/WMS»).
"""
import sqlalchemy as sa
from alembic import op

revision = "0068"
down_revision = "0067"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "stock_threshold",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("sku_code", sa.String(64), nullable=False),
        sa.Column("warehouse", sa.String(128), server_default="Главный", nullable=False),
        sa.Column("min_qty", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.Column("reorder_qty", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.Column("active", sa.Boolean(), server_default="true", nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_stock_threshold")),
        schema="wms",
    )
    op.create_index(
        op.f("ix_wms_stock_threshold_sku_code"), "stock_threshold", ["sku_code"], schema="wms"
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_wms_stock_threshold_sku_code"), "stock_threshold", schema="wms")
    op.drop_table("stock_threshold", schema="wms")
