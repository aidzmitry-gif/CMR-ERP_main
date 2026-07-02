"""leads: схема и таблица лидов (вынос вертикали лидов в отдельный модуль)

Revision ID: 0044
Revises: 0043
Create Date: 2026-06-24
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0044"
down_revision = "0043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS leads")
    op.create_table(
        "lead",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source", sa.String(length=16), server_default="site", nullable=False),
        sa.Column("name", sa.String(length=255), server_default="", nullable=False),
        sa.Column("company", sa.String(length=255), server_default="", nullable=False),
        sa.Column("phone", sa.String(length=64), nullable=True),
        sa.Column("email", sa.String(length=128), nullable=True),
        sa.Column("region", sa.String(length=64), server_default="", nullable=False),
        sa.Column("product", sa.String(length=128), server_default="", nullable=False),
        sa.Column("message", sa.Text(), server_default="", nullable=False),
        sa.Column("status", sa.String(length=16), server_default="new", nullable=False),
        sa.Column("score", sa.Integer(), server_default="0", nullable=False),
        sa.Column("qualification", sa.String(length=16), server_default="", nullable=False),
        sa.Column("reason", sa.String(length=255), server_default="", nullable=False),
        sa.Column("assigned_to", sa.String(length=128), server_default="", nullable=False),
        sa.Column("funnel", sa.String(length=16), server_default="", nullable=False),
        sa.Column("deal_id", sa.Integer(), nullable=True),  # мягкая ссылка на sales.deal (cross-schema, без FK)
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        schema="leads",
    )
    op.create_index("ix_lead_status", "lead", ["status"], schema="leads")


def downgrade() -> None:
    op.drop_index("ix_lead_status", table_name="lead", schema="leads")
    op.drop_table("lead", schema="leads")
    op.execute("DROP SCHEMA IF EXISTS leads")
