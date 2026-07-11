"""sales: конструктор месячного плана продавца — снапшот строк plan_item.

``plan_item`` — строка декомпозиции месячного плана (источник: committed/regular/activity),
снапшот целиком на (owner_id, period_key), заменяется целиком через ``PUT /plan-items``.
Отправка РОПу — существующим ``PlanTarget`` (сумма строк → gross_profit), эта таблица в
approvals не участвует.

Revision ID: 0102
Revises: 0101
Create Date: 2026-07-12
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0102"
down_revision = "0101"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "plan_item",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("period_key", sa.String(10), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("ref", sa.String(64), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("when_label", sa.String(64), nullable=False, server_default=""),
        sa.Column("revenue", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("gross", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("probability", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        schema="sales",
    )


def downgrade() -> None:
    op.drop_table("plan_item", schema="sales")
