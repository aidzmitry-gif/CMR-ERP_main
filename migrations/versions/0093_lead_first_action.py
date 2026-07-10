"""leads: first_action_at на лиде (SLA первой реакции).

Цикл 1 ускорения обработки лидов: время первого действия лидоруба над лидом
(``/qualify``, ``/route`` или ``/reject`` — какое случится раньше) — NULL, пока
лид лежит нетронутым в «Новых». Фронт считает по нему время ожидания реакции.

Revision ID: 0093
Revises: 0092
Create Date: 2026-07-11
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0093"
down_revision = "0092"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "lead",
        sa.Column("first_action_at", sa.DateTime(), nullable=True),
        schema="leads",
    )


def downgrade() -> None:
    op.drop_column("lead", "first_action_at", schema="leads")
