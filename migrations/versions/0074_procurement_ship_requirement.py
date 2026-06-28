"""procurement: ship_requirement — срок отгрузки клиенту из продаж (sales → procurement)

Локальный кэш закупок требований клиента по (сделка, sku): крайняя дата отгрузки + штраф.
Наполняется из события ``sales.deal.ship_deadline.set``. Машина планируется к самому раннему
сроку позиций − буфер «последней мили» (иначе риск срыва отгрузки и штрафа). soft-ref на
sales.deal по deal_id (без cross-schema FK). UNIQUE (deal_id, sku_code).

Revision ID: 0074
Revises: 0073
Create Date: 2026-06-28

Примечание: номер взят атомарно scripts/next_migration.py (procurement); down_revision — реальный head.
"""
import sqlalchemy as sa
from alembic import op

revision = "0074"
down_revision = "0073"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ship_requirement",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("deal_id", sa.Integer(), nullable=False),
        sa.Column("number", sa.String(64), server_default="", nullable=False),
        sa.Column("counterparty", sa.String(255), server_default="", nullable=False),
        sa.Column("sku_code", sa.String(64), nullable=False),
        sa.Column("qty", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.Column("ship_deadline", sa.String(32), nullable=True),
        sa.Column("ship_deadline_date", sa.Date(), nullable=True),
        sa.Column("penalty_rate_pct", sa.Numeric(6, 2), nullable=True),
        sa.Column("penalty_cap_pct", sa.Numeric(6, 2), nullable=True),
        sa.Column("penalty_terms", sa.String(512), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ship_requirement")),
        sa.UniqueConstraint("deal_id", "sku_code", name=op.f("uq_ship_requirement_deal_id")),
        schema="procurement",
    )
    op.create_index(
        "ix_ship_requirement_sku", "ship_requirement", ["sku_code"], schema="procurement"
    )


def downgrade() -> None:
    op.drop_index("ix_ship_requirement_sku", "ship_requirement", schema="procurement")
    op.drop_table("ship_requirement", schema="procurement")
