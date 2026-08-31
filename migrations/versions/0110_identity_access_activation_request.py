"""identity: durable request for onboarding activation

Revision ID: 0110
Revises: 0109
Create Date: 2026-08-31
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0110"
down_revision = "0109"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "identity_access_activation_request",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("expected_department", sa.String(length=128), nullable=False),
        sa.Column("expected_role", sa.String(length=64), nullable=False),
        sa.Column("actor", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=24), server_default="sending", nullable=False),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("activated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["app_user.id"],
            name=op.f("fk_identity_access_activation_request_user_id_app_user"),
        ),
        sa.UniqueConstraint(
            "idempotency_key", name=op.f("uq_identity_access_activation_request_idempotency_key")
        ),
        sa.UniqueConstraint(
            "user_id", name=op.f("uq_identity_access_activation_request_user_id")
        ),
        sa.UniqueConstraint(
            "employee_id", name=op.f("uq_identity_access_activation_request_employee_id")
        ),
    )


def downgrade() -> None:
    op.drop_table("identity_access_activation_request")
