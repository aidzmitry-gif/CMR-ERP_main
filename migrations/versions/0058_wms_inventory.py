"""wms: инвентаризация (пересчёт склада со сверкой против 1С)

``wms.inventory_count`` — документ инвентаризации (склад, статус open|done|canceled);
``wms.inventory_line`` — строка: SKU, ожидаемое (снимок 1С) + себес, факт пересчёта.
Расхождение (недостача/излишек) и его денежная оценка считаются на чтение. WMS НЕ
источник истины остатка (1С — истина, фаза 1): документ читает ожидаемое через шлюз
остатков и фиксирует факт; корректировка остатков 1С заморожена до фазы 2.

Revision ID: 0058
Revises: 0057
Create Date: 2026-06-27

Примечание: номер взят атомарно через scripts/next_migration.py (полоса «Склад/WMS»).
Чейн: 0055 → 0056 (procurement) → 0057 (reference) → 0058 (этот). 0056 ранее был выдан
устно ошибочно — перенумеровано в 0058 по аллокатору (единственный источник истины).
"""
import sqlalchemy as sa
from alembic import op

revision = "0058"
down_revision = "0057"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "inventory_count",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("number", sa.String(64), server_default="", nullable=False),
        sa.Column("warehouse", sa.String(128), server_default="Главный", nullable=False),
        sa.Column("status", sa.String(16), server_default="open", nullable=False),
        sa.Column("note", sa.String(512), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inventory_count")),
        schema="wms",
    )
    op.create_table(
        "inventory_line",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("count_id", sa.Integer(), nullable=False),
        sa.Column("sku_code", sa.String(64), nullable=False),
        sa.Column("sku_title", sa.String(255), server_default="", nullable=False),
        sa.Column("unit", sa.String(16), server_default="шт", nullable=False),
        sa.Column("expected_qty", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.Column("counted_qty", sa.Numeric(14, 2), nullable=True),
        sa.Column("unit_cost", sa.Numeric(14, 2), nullable=True),
        sa.Column("note", sa.String(512), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["count_id"],
            ["wms.inventory_count.id"],
            name=op.f("fk_inventory_line_count_id_inventory_count"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inventory_line")),
        schema="wms",
    )
    op.create_index(
        op.f("ix_wms_inventory_line_count_id"), "inventory_line", ["count_id"], schema="wms"
    )
    op.create_index(
        op.f("ix_wms_inventory_line_sku_code"), "inventory_line", ["sku_code"], schema="wms"
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_wms_inventory_line_sku_code"), "inventory_line", schema="wms")
    op.drop_index(op.f("ix_wms_inventory_line_count_id"), "inventory_line", schema="wms")
    op.drop_table("inventory_line", schema="wms")
    op.drop_table("inventory_count", schema="wms")
