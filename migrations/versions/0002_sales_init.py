"""sales: схема и таблица сделок

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-02
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS sales")
    op.create_table(
        "deal",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("number", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("counterparty", sa.String(length=255), nullable=False),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), server_default="0", nullable=False),
        sa.Column("stage", sa.String(length=64), server_default="Новая заявка", nullable=False),
        sa.Column("priority", sa.String(length=32), server_default="Средний", nullable=False),
        sa.UniqueConstraint("number", name=op.f("uq_deal_number")),
        schema="sales",
    )


def downgrade() -> None:
    op.drop_table("deal", schema="sales")
    op.execute("DROP SCHEMA IF EXISTS sales")
