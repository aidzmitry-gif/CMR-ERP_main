"""procurement: origin заявки (MRP-lite) + received_at заказа (своевременность)

- ``purchase_request.origin`` (String(32), '') — источник заявки: '' ручная / 'deficit'
  автозаявка по сигналу дефицита склада (``wms.stock.low`` → MRP-lite, круг 3).
- ``purchase_order.received_at`` (DateTime|None) — факт приёмки (статус → received); основа
  своевременности поставщика (ETA vs факт) в scorecard + переход landed cost estimated→actual.

Обе колонки аддитивны (старые строки не ломаются). Одна ревизия круга 3 (см. контракт-фриз).

Revision ID: 0071
Revises: 0070
Create Date: 2026-06-28

Примечание: номер взят атомарно scripts/next_migration.py (procurement); down_revision — реальный head.
"""
import sqlalchemy as sa
from alembic import op

revision = "0071"
down_revision = "0070"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "purchase_request",
        sa.Column("origin", sa.String(32), server_default="", nullable=False),
        schema="procurement",
    )
    op.add_column(
        "purchase_order",
        sa.Column("received_at", sa.DateTime(), nullable=True),
        schema="procurement",
    )


def downgrade() -> None:
    op.drop_column("purchase_order", "received_at", schema="procurement")
    op.drop_column("purchase_request", "origin", schema="procurement")
