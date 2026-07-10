"""leads: lead_item — позиции подбора товара на лиде (КП до сделки).

Спец по лидам подбирает товар прямо во время общения с клиентом (тот же каталог-пикер,
что и в сделках) — подбор оседает здесь как коммерческое предложение. При конвертации
«В сделку + счёт» позиции переносит в ``sales.deal_item`` фронт (addDealItem), а сама
таблица живёт только на стороне лида. FK на ``leads.lead`` — в одной схеме, ON DELETE
CASCADE (как ``lead_attachment`` 0091): удалили лид — ушёл и его подбор.

``sku_id`` — мягкая ссылка на shared-kernel ``Sku`` (как ``sales.deal_item``, без
cross-schema FK); ``price`` — цена клиенту (уже со скидкой), ``discount_pct`` — скидка
справочно (сумма КП = qty*price).

Revision ID: 0094
Revises: 0093
Create Date: 2026-07-11
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0094"
down_revision = "0093"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lead_item",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "lead_id",
            sa.Integer(),
            sa.ForeignKey("leads.lead.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sku_id", sa.Integer(), nullable=False),
        sa.Column("sku_code", sa.String(length=64), server_default="", nullable=False),
        sa.Column("name", sa.String(length=255), server_default="", nullable=False),
        sa.Column("qty", sa.Numeric(14, 2), server_default="1", nullable=False),
        sa.Column("price", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.Column("discount_pct", sa.Numeric(6, 2), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        schema="leads",
    )
    op.create_index("ix_lead_item_lead_id", "lead_item", ["lead_id"], schema="leads")


def downgrade() -> None:
    op.drop_index("ix_lead_item_lead_id", table_name="lead_item", schema="leads")
    op.drop_table("lead_item", schema="leads")
