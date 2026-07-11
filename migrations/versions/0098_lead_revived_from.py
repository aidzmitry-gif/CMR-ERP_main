"""leads: ссылка на ранее отклонённый лид того же контакта (Цикл 12 — реанимация памяти).

``revived_from_id`` — если новый лид пришёл от контакта, которого раньше уже отклоняли,
он ссылается на тот отклонённый лид. Продавец видит историю («был отказ: нет бюджета»),
а не работает вслепую. Мягкая ссылка внутри схемы leads (без каскада — история важна).

Revision ID: 0098
Revises: 0097
Create Date: 2026-07-11
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0098"
down_revision = "0097"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("lead", sa.Column("revived_from_id", sa.Integer(), nullable=True), schema="leads")


def downgrade() -> None:
    op.drop_column("lead", "revived_from_id", schema="leads")
