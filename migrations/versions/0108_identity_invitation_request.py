"""identity: журнал однократной отправки приглашения

Храним заявку до внешнего вызова Keycloak. Это даёт безопасную идемпотентность:
после сетевой ошибки автоматизация не отправляет второе письмо вслепую.

Revision ID: 0108
Revises: 0107
Create Date: 2026-08-31
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0108"
down_revision = "0107"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "identity_invitation_request",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("username", sa.String(length=128), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("department", sa.String(length=128), nullable=False),
        sa.Column("role", sa.String(length=64), nullable=False),
        sa.Column("actor", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=24), server_default="sending", nullable=False),
        sa.Column("keycloak_user_id", sa.String(length=64), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["app_user.id"], name=op.f("fk_identity_invitation_request_user_id_app_user")
        ),
        sa.UniqueConstraint(
            "idempotency_key", name=op.f("uq_identity_invitation_request_idempotency_key")
        ),
        sa.UniqueConstraint(
            "employee_id", name=op.f("uq_identity_invitation_request_employee_id")
        ),
        sa.UniqueConstraint(
            "user_id", name=op.f("uq_identity_invitation_request_user_id")
        ),
    )


def downgrade() -> None:
    op.drop_table("identity_invitation_request")
