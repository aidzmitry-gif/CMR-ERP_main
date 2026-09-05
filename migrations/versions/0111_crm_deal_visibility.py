"""identity/sales: per-employee deal visibility

Revision ID: 0111
Revises: 0110
Create Date: 2026-09-05
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0111"
down_revision = "0110"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ``all`` preserves the pre-feature behaviour for every existing account.
    op.add_column(
        "app_user",
        sa.Column("deal_visibility", sa.String(length=8), server_default="all", nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_app_user_deal_visibility"),
        "app_user",
        "deal_visibility IN ('all', 'own')",
    )
    op.add_column(
        "deal",
        sa.Column("owner_id", sa.Integer(), nullable=True),
        schema="sales",
    )
    op.create_index(
        op.f("ix_sales_deal_owner_id"),
        "deal",
        ["owner_id"],
        schema="sales",
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_sales_deal_owner_id"), table_name="deal", schema="sales")
    op.drop_column("deal", "owner_id", schema="sales")
    op.drop_constraint(op.f("ck_app_user_deal_visibility"), "app_user", type_="check")
    op.drop_column("app_user", "deal_visibility")
