"""knowledge: таблица course_enrollment — назначение курса сотруднику (учёт курсов).

Revision ID: 0086
Revises: 0085
Create Date: 2026-07-02
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0086"
down_revision = "0085"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "course_enrollment",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("course_id", sa.Integer(), nullable=False),
        sa.Column("employee_name", sa.String(255), nullable=False, server_default=""),
        sa.Column("status", sa.String(32), nullable=False, server_default="assigned"),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("assigned_at", sa.String(10), nullable=True),
        sa.Column("completed_at", sa.String(10), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        schema="knowledge",
    )


def downgrade() -> None:
    op.drop_table("course_enrollment", schema="knowledge")
