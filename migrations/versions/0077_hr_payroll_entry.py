"""hr: таблица payroll_entry — начисление/выплата ФОТ сотрудникам.

Revision ID: 0077
Revises: 0076
Create Date: 2026-06-29
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0077"
down_revision = "0076"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "payroll_entry",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("hr.employee.id"), nullable=False),
        sa.Column("period", sa.String(7), nullable=False),
        sa.Column("amount_byn", sa.String(20), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        schema="hr",
    )


def downgrade() -> None:
    op.drop_table("payroll_entry", schema="hr")
