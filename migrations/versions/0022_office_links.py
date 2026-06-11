"""office: связи отделов, доставка, заявка перевозчику, эскалация

Аддитивные колонки к ``office.office_doc`` (таблица создана в 0019):
доставка (region/weight/address), следы связей с отделами (*_ref) и
счётчик просрочки оплаты (overdue_days). Все — с ``server_default``,
поэтому миграция безопасна для существующих строк.

Revision ID: 0022
Revises: 0021
Create Date: 2026-06-11
"""
import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None

# Новые колонки: имя → SQLAlchemy-тип + server_default (все NOT NULL).
_STRING_COLS = (
    ("region", 64),       # направление доставки по РБ
    ("weight", 32),       # вес/габарит груза
    ("address", 255),     # адрес выдачи
    ("sales_ref", 64),    # ← CRM (sales.deal.won)
    ("wms_ref", 64),      # ↔ Склад (приёмка/сборка/отгрузка)
    ("logistics_ref", 64),  # → Логистика (заявка перевозчику)
    ("finance_ref", 64),  # ↔ Финансы (счёт/оплата)
    ("legal_ref", 64),    # → Юрист (претензия по просрочке)
)


def upgrade() -> None:
    for name, length in _STRING_COLS:
        op.add_column(
            "office_doc",
            sa.Column(name, sa.String(length=length), server_default="", nullable=False),
            schema="office",
        )
    op.add_column(
        "office_doc",
        sa.Column("overdue_days", sa.Integer(), server_default="0", nullable=False),
        schema="office",
    )


def downgrade() -> None:
    op.drop_column("office_doc", "overdue_days", schema="office")
    for name, _ in reversed(_STRING_COLS):
        op.drop_column("office_doc", name, schema="office")
