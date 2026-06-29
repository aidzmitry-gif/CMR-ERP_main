"""office: таблица legal_contract — реестр юридических договоров.

Revision ID: 0079
Revises: 0078
Create Date: 2026-06-29
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0079"
down_revision = "0078"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "legal_contract",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("number", sa.String(64), nullable=False, server_default=""),
        sa.Column("counterparty_name", sa.String(255), nullable=False, server_default=""),
        sa.Column("contract_type", sa.String(64), nullable=False, server_default="supply"),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("signed_at", sa.String(10), nullable=True),
        sa.Column("expires_at", sa.String(10), nullable=True),
        sa.Column("amount_byn", sa.String(20), nullable=False, server_default="0.00"),
        sa.Column("description", sa.String(500), nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        schema="office",
    )


def downgrade() -> None:
    op.drop_table("legal_contract", schema="office")
