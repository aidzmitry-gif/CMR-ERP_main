"""hr: таблица okk_score — ОКК-оценки сотрудников по категориям.

Revision ID: 0078
Revises: 0077
Create Date: 2026-06-29
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0078"
down_revision = "0077"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "okk_score",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("hr.employee.id"), nullable=False),
        sa.Column("period", sa.String(7), nullable=False),
        sa.Column("discipline", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("quality", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("service", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("teamwork", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("comment", sa.String(500), nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        schema="hr",
    )


def downgrade() -> None:
    op.drop_table("okk_score", schema="hr")
