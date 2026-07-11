"""leads: недозвон как состояние + повторное касание (Цикл 15).

``attempt_count``/``callback_at`` — счётчик попыток контакта и срок перезвона: недозвонённый
целевой лид не гниёт молча, а живёт в очереди «перезвонить к…» (стандарт — до 6 попыток).
``last_touch_at`` — повторное касание клиента (дубль-звонок/повторная заявка): бейдж
«↑ повтор» и подъём лида — повтор конвертируется в разы лучше первого касания.

Revision ID: 0100
Revises: 0099
Create Date: 2026-07-11
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0100"
down_revision = "0099"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "lead",
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        schema="leads",
    )
    op.add_column("lead", sa.Column("callback_at", sa.DateTime(), nullable=True), schema="leads")
    op.add_column("lead", sa.Column("last_touch_at", sa.DateTime(), nullable=True), schema="leads")


def downgrade() -> None:
    op.drop_column("lead", "last_touch_at", schema="leads")
    op.drop_column("lead", "callback_at", schema="leads")
    op.drop_column("lead", "attempt_count", schema="leads")
