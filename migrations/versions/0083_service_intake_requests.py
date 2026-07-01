"""service: таблица service_request — заявки на обслуживание (+ auto-intake из sales.deal.won)

Revision ID: 0083
Revises: 0082
Create Date: 2026-07-02
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0083"
down_revision = "0082"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS service")
    op.create_table(
        "service_request",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("counterparty_id", sa.Integer(), nullable=True),
        sa.Column("deal_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("status", sa.String(32), server_default="new", nullable=False),
        sa.Column("priority", sa.String(32), server_default="normal", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        schema="service",
    )


def downgrade() -> None:
    op.drop_table("service_request", schema="service")
