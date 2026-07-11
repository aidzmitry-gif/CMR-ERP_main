"""leads: дневная норма лидоруба + момент конвертации (Цикл 5 — план/факт).

Две связанные вещи для дневного план/факта специалиста по лидам:
- таблица ``leads.lead_plan`` — «вечнозелёная» дневная норма (одна строка на период),
  к которой меряется факт за сегодня;
- колонка ``lead.converted_at`` — момент конвертации, чтобы «доведено до сделки сегодня»
  можно было посчитать по времени (у ``first_action_at`` иная семантика — первое действие).

Revision ID: 0096
Revises: 0095
Create Date: 2026-07-11
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0096"
down_revision = "0095"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "lead",
        sa.Column("converted_at", sa.DateTime(), nullable=True),
        schema="leads",
    )
    op.create_table(
        "lead_plan",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("period", sa.String(length=16), server_default="daily", nullable=False),
        sa.Column("leads_target", sa.Integer(), server_default="20", nullable=False),
        sa.Column("qualified_target", sa.Integer(), server_default="8", nullable=False),
        sa.Column("converted_target", sa.Integer(), server_default="3", nullable=False),
        sa.Column("reaction_target_min", sa.Integer(), server_default="15", nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("period", name="uq_lead_plan_period"),
        schema="leads",
    )


def downgrade() -> None:
    op.drop_table("lead_plan", schema="leads")
    op.drop_column("lead", "converted_at", schema="leads")
