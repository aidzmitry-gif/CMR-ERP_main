"""sales: крайняя дата отгрузки + штрафные санкции за опоздание (Deal)

Добавляет в ``sales.deal``:
- ``ship_deadline`` (String(32), nullable) — крайняя дата отгрузки клиенту (уходит сигналом
  в закупки через ``sales.deal.ship_deadline.set``);
- гибрид штрафа за опоздание: ``penalty_rate_pct`` (Numeric(6,2)) ставка %/день просрочки,
  ``penalty_cap_pct`` (Numeric(6,2)) потолок % от суммы, ``penalty_terms`` (String(512))
  свободное примечание.
Все колонки опциональны (nullable) — существующие сделки остаются валидны.

Revision ID: 0073
Revises: 0072
Create Date: 2026-06-28

Примечание: номер взят атомарно через scripts/next_migration.py (полоса CRM/Продажи).
"""
import sqlalchemy as sa
from alembic import op

revision = "0073"
down_revision = "0072"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "deal", sa.Column("ship_deadline", sa.String(32), nullable=True), schema="sales"
    )
    op.add_column(
        "deal", sa.Column("penalty_rate_pct", sa.Numeric(6, 2), nullable=True), schema="sales"
    )
    op.add_column(
        "deal", sa.Column("penalty_cap_pct", sa.Numeric(6, 2), nullable=True), schema="sales"
    )
    op.add_column(
        "deal", sa.Column("penalty_terms", sa.String(512), nullable=True), schema="sales"
    )


def downgrade() -> None:
    op.drop_column("deal", "penalty_terms", schema="sales")
    op.drop_column("deal", "penalty_cap_pct", schema="sales")
    op.drop_column("deal", "penalty_rate_pct", schema="sales")
    op.drop_column("deal", "ship_deadline", schema="sales")
