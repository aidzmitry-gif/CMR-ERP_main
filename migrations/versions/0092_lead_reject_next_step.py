"""leads: reject_reason + next_step_at/next_step_note на лиде.

Слайс 4 кокпита лида: статус ``rejected`` уже упоминался в докстринге Lead,
но без реализации — этой миграцией добавляется поле для причины отказа.
``next_step_at``/``next_step_note`` — срок и заметка для продавца, выставляются
при раздаче (``POST /leads/{id}/route``), не только при ручном выборе.

Revision ID: 0092
Revises: 0091
Create Date: 2026-07-04
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0092"
down_revision = "0091"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "lead",
        sa.Column("reject_reason", sa.String(length=255), server_default="", nullable=False),
        schema="leads",
    )
    op.add_column(
        "lead",
        sa.Column("next_step_at", sa.DateTime(), nullable=True),
        schema="leads",
    )
    op.add_column(
        "lead",
        sa.Column("next_step_note", sa.Text(), server_default="", nullable=False),
        schema="leads",
    )


def downgrade() -> None:
    op.drop_column("lead", "next_step_note", schema="leads")
    op.drop_column("lead", "next_step_at", schema="leads")
    op.drop_column("lead", "reject_reason", schema="leads")
