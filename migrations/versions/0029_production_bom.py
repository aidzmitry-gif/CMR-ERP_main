"""production: спецификации · BOM (состав изделий + обеспеченность)

Две новые таблицы схемы ``production``:
- ``production_bom`` — спецификация изделия (черновик/утверждена);
- ``production_bom_item`` — позиции состава (комплектующее, норма расхода,
  остаток, резерв) по ``bom_id`` (индекс, без FK-связи — в духе модуля).

Revision ID: 0029
Revises: 0028
Create Date: 2026-06-11
"""
import sqlalchemy as sa
from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "production_bom",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product", sa.String(length=255), nullable=False),
        sa.Column("version", sa.String(length=16), server_default="v1", nullable=False),
        sa.Column("status", sa.String(length=16), server_default="draft", nullable=False),
        sa.Column("note", sa.String(length=400), server_default="", nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        schema="production",
    )
    op.create_table(
        "production_bom_item",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("bom_id", sa.Integer(), nullable=False),
        sa.Column("component", sa.String(length=255), nullable=False),
        sa.Column("norm_qty", sa.Float(), server_default="0", nullable=False),
        sa.Column("unit", sa.String(length=32), server_default="шт", nullable=False),
        sa.Column("stock", sa.Float(), server_default="0", nullable=False),
        sa.Column("reserved", sa.Float(), server_default="0", nullable=False),
        schema="production",
    )
    op.create_index(
        "ix_production_bom_item_bom_id",
        "production_bom_item",
        ["bom_id"],
        schema="production",
    )


def downgrade() -> None:
    op.drop_index("ix_production_bom_item_bom_id", table_name="production_bom_item", schema="production")
    op.drop_table("production_bom_item", schema="production")
    op.drop_table("production_bom", schema="production")
