"""procurement: landed cost per-SKU + открытый заказ (PurchaseOrder/Line)

Денежная полоса: разблокирует маржу sales. Закупки публикуют себестоимость единицы
номенклатуры (BYN), доведённой до склада, через read-only фасад ``core.services.landed_cost``;
sales читает её для расчёта маржи (``quote_line``). Открытый заказ с ETA даёт sales «в пути».

- ``procurement.purchase_order`` / ``purchase_order_line`` — размещённый заказ с позициями
  (``sku_code+qty+стоимость+вес/объём``), статусом и ETA. На приёмке (``received``) общий движок
  ``allocate_landed_cost`` разносит фрахт на позиции → строки ``landed_cost`` per-SKU.
- ``procurement.landed_cost`` — результат распределения: себестоимость единицы по ``sku_code``
  (своя схема procurement; ``integrations.batch.unit_landed_cost`` — поле СИНК, НЕ дублируем).

Revision ID: 0056
Revises: 0055
Create Date: 2026-06-27

Примечание: чейн линейный 0055 → 0056 (закупки готовы первыми; WMS чейнится 0057).
"""
import sqlalchemy as sa
from alembic import op

revision = "0056"
down_revision = "0055"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "purchase_order",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("number", sa.String(64), server_default="", nullable=False),
        sa.Column("supplier", sa.String(255), server_default="", nullable=False),
        sa.Column("status", sa.String(16), server_default="ordered", nullable=False),
        sa.Column("eta_date", sa.Date(), nullable=True),
        sa.Column("freight_byn", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_purchase_order")),
        schema="procurement",
    )
    op.create_table(
        "purchase_order_line",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("sku_code", sa.String(64), nullable=False),
        sa.Column("qty", sa.Numeric(14, 2), server_default="1", nullable=False),
        sa.Column("goods_value_byn", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.Column("weight", sa.Numeric(14, 3), server_default="0", nullable=False),
        sa.Column("volume", sa.Numeric(14, 4), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["procurement.purchase_order.id"],
            name=op.f("fk_purchase_order_line_order_id_purchase_order"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_purchase_order_line")),
        schema="procurement",
    )
    op.create_index(
        "ix_purchase_order_line_order",
        "purchase_order_line",
        ["order_id"],
        schema="procurement",
    )
    op.create_table(
        "landed_cost",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("sku_code", sa.String(64), nullable=False),
        sa.Column("purchase_order_id", sa.Integer(), nullable=True),
        sa.Column("shipment_id", sa.String(64), server_default="", nullable=False),
        sa.Column("unit_landed_cost_byn", sa.Numeric(14, 4), nullable=False),
        sa.Column("stage", sa.String(16), server_default="estimated", nullable=False),
        sa.Column("fx_rate", sa.Numeric(18, 6), nullable=True),
        sa.Column("fx_date", sa.Date(), nullable=True),
        sa.Column("fx_rate_basis", sa.String(8), nullable=True),
        sa.Column("fixed_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_landed_cost")),
        sa.UniqueConstraint(
            "sku_code", "purchase_order_id", name=op.f("uq_landed_cost_sku_code")
        ),
        schema="procurement",
    )
    op.create_index(
        "ix_landed_cost_sku_fixed",
        "landed_cost",
        ["sku_code", "fixed_at"],
        schema="procurement",
    )


def downgrade() -> None:
    op.drop_index("ix_landed_cost_sku_fixed", "landed_cost", schema="procurement")
    op.drop_table("landed_cost", schema="procurement")
    op.drop_index("ix_purchase_order_line_order", "purchase_order_line", schema="procurement")
    op.drop_table("purchase_order_line", schema="procurement")
    op.drop_table("purchase_order", schema="procurement")
