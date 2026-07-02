"""finance: Р5 — entity_ref + description в finance.payment.

Revision ID: 0076
Revises: 0075
Create Date: 2026-06-29
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0076"
down_revision = "0075"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("payment", schema="finance") as batch_op:
        batch_op.add_column(
            sa.Column("entity_ref", sa.String(128), nullable=True)
        )
        batch_op.add_column(
            sa.Column("description", sa.String(255), nullable=True)
        )
        batch_op.create_index(
            "ix_finance_payment_entity_ref", ["entity_ref"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("payment", schema="finance") as batch_op:
        batch_op.drop_index("ix_finance_payment_entity_ref")
        batch_op.drop_column("description")
        batch_op.drop_column("entity_ref")
