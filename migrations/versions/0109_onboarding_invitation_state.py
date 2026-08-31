"""identity: onboarding-режим до подтверждения руководителя

Рабочие отдел и роль приглашённого сотрудника хранятся отдельно от
действующих полей ``app_user.department`` / ``app_user.role``. Это исключает
случайную выдачу бизнес-доступа при создании приглашения.

Revision ID: 0109
Revises: 0108
Create Date: 2026-08-31
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0109"
down_revision = "0108"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "app_user", sa.Column("expected_department", sa.String(length=128), nullable=True)
    )
    op.add_column("app_user", sa.Column("expected_role", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("app_user", "expected_role")
    op.drop_column("app_user", "expected_department")
