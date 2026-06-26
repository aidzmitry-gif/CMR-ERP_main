"""integrations: себестоимость на остатке 1С (маржа «в наличии»)

``integrations.stock_item.cost`` — себестоимость из 1С (nullable; None — 1С не дал
себес). Маржа позиции «в наличии» = (цена − себес)/цена — методика цены
(pricing-calculation-todo): в наличии → себес и цена из 1С.

Revision ID: 0051
Revises: 0050
Create Date: 2026-06-26

Примечание: чейн линейный 0050 → 0051. Если параллельная сессия уже заняла 0051 —
перенумеровать (как было с 0034/0036).
"""
import sqlalchemy as sa
from alembic import op

revision = "0051"
down_revision = "0050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "stock_item",
        sa.Column("cost", sa.Numeric(14, 2), nullable=True),
        schema="integrations",
    )


def downgrade() -> None:
    op.drop_column("stock_item", "cost", schema="integrations")
