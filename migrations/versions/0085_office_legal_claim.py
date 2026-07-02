"""office: таблица legal_claim — реестр юридических претензий.

Revision ID: 0085
Revises: 0084
Create Date: 2026-07-02
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0085"
down_revision = "0084"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "legal_claim",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("number", sa.String(64), nullable=False, server_default=""),
        sa.Column("counterparty_name", sa.String(255), nullable=False, server_default=""),
        sa.Column("claim_type", sa.String(64), nullable=False, server_default="overdue_payment"),
        sa.Column("status", sa.String(32), nullable=False, server_default="open"),
        sa.Column("amount_byn", sa.String(20), nullable=False, server_default="0.00"),
        sa.Column("filed_at", sa.String(10), nullable=True),
        sa.Column("resolved_at", sa.String(10), nullable=True),
        sa.Column("description", sa.String(500), nullable=False, server_default=""),
        sa.Column("office_doc_ref", sa.String(64), nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        schema="office",
    )


def downgrade() -> None:
    op.drop_table("legal_claim", schema="office")
