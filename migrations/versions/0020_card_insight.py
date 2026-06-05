"""funnels: AI-инсайт карточки (procurement / production)

Добавляет колонку ``insight`` (AI-рекомендация по карточке) в закупки и наряды.

Revision ID: 0020
Revises: 0019
Create Date: 2026-06-05
"""
import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "purchase_request",
        sa.Column("insight", sa.String(length=400), server_default="", nullable=False),
        schema="procurement",
    )
    op.add_column(
        "production_order",
        sa.Column("insight", sa.String(length=400), server_default="", nullable=False),
        schema="production",
    )


def downgrade() -> None:
    op.drop_column("production_order", "insight", schema="production")
    op.drop_column("purchase_request", "insight", schema="procurement")
