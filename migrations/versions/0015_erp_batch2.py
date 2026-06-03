"""erp: модули Логистика / Финансы / Маркетинг

Revision ID: 0015
Revises: 0014
Create Date: 2026-06-03
"""
import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS logistics")
    op.create_table(
        "shipment",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("customer", sa.String(length=255), nullable=False),
        sa.Column("address", sa.String(length=255), server_default="", nullable=False),
        sa.Column("carrier", sa.String(length=128), server_default="", nullable=False),
        sa.Column("status", sa.String(length=32), server_default="planned", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        schema="logistics",
    )

    op.execute("CREATE SCHEMA IF NOT EXISTS finance")
    op.create_table(
        "payment",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ref", sa.String(length=255), nullable=False),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), server_default="0", nullable=False),
        sa.Column("status", sa.String(length=32), server_default="pending", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        schema="finance",
    )

    op.execute("CREATE SCHEMA IF NOT EXISTS marketing")
    op.create_table(
        "campaign",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("channel", sa.String(length=64), server_default="", nullable=False),
        sa.Column("budget", sa.Numeric(precision=14, scale=2), server_default="0", nullable=False),
        sa.Column("leads", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        schema="marketing",
    )


def downgrade() -> None:
    op.drop_table("campaign", schema="marketing")
    op.execute("DROP SCHEMA IF EXISTS marketing")
    op.drop_table("payment", schema="finance")
    op.execute("DROP SCHEMA IF EXISTS finance")
    op.drop_table("shipment", schema="logistics")
    op.execute("DROP SCHEMA IF EXISTS logistics")
