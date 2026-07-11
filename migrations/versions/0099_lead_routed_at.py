"""leads: момент передачи продавцу (Цикл 13 — пост-передача под контролем).

``routed_at`` — когда лид ушёл продавцу (/route, /express, /express-bulk). Даёт возраст
«у продавца» на карточке и подсветку зависших >24ч в скорборде передач: дожим сегодня,
а не постфактум. У лидов, распределённых до миграции, остаётся NULL (возраст не показываем).

Revision ID: 0099
Revises: 0098
Create Date: 2026-07-11
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0099"
down_revision = "0098"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("lead", sa.Column("routed_at", sa.DateTime(), nullable=True), schema="leads")


def downgrade() -> None:
    op.drop_column("lead", "routed_at", schema="leads")
