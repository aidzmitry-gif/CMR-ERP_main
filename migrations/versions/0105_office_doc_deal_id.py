"""office: ручка сделки на документе — office_doc.deal_id (шов «оплата → офис»)

Документ офиса заводится по ``sales.deal.won`` и хранил только ``sales_ref`` = НОМЕР
сделки (строка). Финансы же шлют ``finance.payment.received`` c ``deal_id`` (целочисленный
ключ сделки) — два разных представления одной сделки, которые никогда не совпадали строкой,
поэтому оплата не двигала документ в «Оплачено» (мёртвый шов). Добавляем целочисленную
ручку ``deal_id`` — общий ключ, по которому финансовое событие находит документ.

Аддитивно и безопасно: колонка nullable (существующие строки → NULL, заполняются с
новых сделок).

Revision ID: 0105
Revises: 0104
Create Date: 2026-07-16
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0105"
down_revision = "0104"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "office_doc", sa.Column("deal_id", sa.Integer(), nullable=True), schema="office"
    )


def downgrade() -> None:
    op.drop_column("office_doc", "deal_id", schema="office")
