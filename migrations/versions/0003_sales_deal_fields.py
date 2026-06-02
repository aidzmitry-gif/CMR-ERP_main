"""sales: дополнительные поля сделки (owner, next_step, даты, флаги)

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-02
"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("deal", sa.Column("owner", sa.String(length=128), server_default="", nullable=False), schema="sales")
    op.add_column("deal", sa.Column("next_step", sa.String(length=128), nullable=True), schema="sales")
    op.add_column("deal", sa.Column("deal_date", sa.String(length=32), nullable=True), schema="sales")
    op.add_column("deal", sa.Column("closed_date", sa.String(length=32), nullable=True), schema="sales")
    op.add_column("deal", sa.Column("focus", sa.Boolean(), server_default=sa.text("false"), nullable=False), schema="sales")
    op.add_column("deal", sa.Column("starred", sa.Boolean(), server_default=sa.text("false"), nullable=False), schema="sales")
    op.alter_column("deal", "stage", server_default="new", schema="sales")


def downgrade() -> None:
    op.alter_column("deal", "stage", server_default="Новая заявка", schema="sales")
    for col in ("starred", "focus", "closed_date", "deal_date", "next_step", "owner"):
        op.drop_column("deal", col, schema="sales")
