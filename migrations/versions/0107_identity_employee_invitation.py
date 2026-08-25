"""identity: связать app_user с HR-сотрудником и Keycloak-приглашением

Revision ID: 0107
Revises: 0106
Create Date: 2026-08-24
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0107"
down_revision = "0106"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("app_user", sa.Column("email", sa.String(length=255), nullable=True))
    op.add_column("app_user", sa.Column("employee_id", sa.Integer(), nullable=True))
    op.add_column("app_user", sa.Column("department", sa.String(length=128), nullable=True))
    op.add_column("app_user", sa.Column("role", sa.String(length=64), nullable=True))
    op.add_column(
        "app_user", sa.Column("keycloak_user_id", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "app_user",
        sa.Column("status", sa.String(length=24), server_default="active", nullable=False),
    )
    op.add_column("app_user", sa.Column("invited_at", sa.DateTime(), nullable=True))
    op.create_unique_constraint(op.f("uq_app_user_email"), "app_user", ["email"])
    op.create_unique_constraint(op.f("uq_app_user_employee_id"), "app_user", ["employee_id"])
    op.create_unique_constraint(
        op.f("uq_app_user_keycloak_user_id"), "app_user", ["keycloak_user_id"]
    )


def downgrade() -> None:
    op.drop_constraint(op.f("uq_app_user_keycloak_user_id"), "app_user", type_="unique")
    op.drop_constraint(op.f("uq_app_user_employee_id"), "app_user", type_="unique")
    op.drop_constraint(op.f("uq_app_user_email"), "app_user", type_="unique")
    op.drop_column("app_user", "invited_at")
    op.drop_column("app_user", "status")
    op.drop_column("app_user", "keycloak_user_id")
    op.drop_column("app_user", "role")
    op.drop_column("app_user", "department")
    op.drop_column("app_user", "employee_id")
    op.drop_column("app_user", "email")
