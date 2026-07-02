"""integrations: партии закупки по SKU (lot/batch + FEFO) — M4.2

``integrations.batch`` — приход товара партиями из 1С/закупок: номер партии поставщика,
поставщик, склад, кол-во, даты производства/годности (FEFO-алерт <1 года), себестоимость
единицы партии (landed cost), внешняя ссылка (ГТД/машина/Ref 1С). Транзакционные данные,
отдельно от мастер-данных ``Sku``; на карточке номенклатуры читаются через фасад stock.

Revision ID: 0052
Revises: 0051
Create Date: 2026-06-26

Примечание: чейн линейный 0051 → 0052. Если параллельная сессия уже заняла 0052 —
перенумеровать (как было с 0034/0036).
"""
import sqlalchemy as sa
from alembic import op

revision = "0052"
down_revision = "0051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "batch",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("sku_code", sa.String(64), nullable=False),
        sa.Column("lot_no", sa.String(64), nullable=False),
        sa.Column("supplier", sa.String(256), nullable=True),
        sa.Column("warehouse", sa.String(128), nullable=True),
        sa.Column("qty", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.Column("mfg_date", sa.Date(), nullable=True),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column("unit_landed_cost", sa.Numeric(14, 2), nullable=True),
        sa.Column("external_ref", sa.String(128), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_batch")),
        schema="integrations",
    )
    op.create_index(
        op.f("ix_integrations_batch_sku_code"), "batch", ["sku_code"], schema="integrations"
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_integrations_batch_sku_code"), "batch", schema="integrations")
    op.drop_table("batch", schema="integrations")
