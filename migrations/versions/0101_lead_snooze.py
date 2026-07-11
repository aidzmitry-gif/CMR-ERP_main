"""leads: рецикл «не сейчас» — дата авто-возврата отложенного лида (Цикл 16).

``snooze_until`` — отказ с причиной «не сейчас» не хоронит лид навсегда: при наступлении
даты (30/90/180 дней) лид сам возвращается в «Новые» (wake-on-read в GET /leads) с бейджем
«⏰ проснулся». 77% некупивших сразу покупают в течение 2 лет — это бесплатные будущие
сделки из уже оплаченной базы.

Revision ID: 0101
Revises: 0100
Create Date: 2026-07-11
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0101"
down_revision = "0100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("lead", sa.Column("snooze_until", sa.DateTime(), nullable=True), schema="leads")


def downgrade() -> None:
    op.drop_column("lead", "snooze_until", schema="leads")
