"""sales: лиды — вход воронки (приём → квалификация → распределение → сделка)

Revision ID: 0018
Revises: 0017
Create Date: 2026-06-03
"""
import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lead",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source", sa.String(length=16), server_default="site", nullable=False),
        sa.Column("name", sa.String(length=255), server_default="", nullable=False),
        sa.Column("company", sa.String(length=255), server_default="", nullable=False),
        sa.Column("phone", sa.String(length=64), nullable=True),
        sa.Column("email", sa.String(length=128), nullable=True),
        sa.Column("region", sa.String(length=64), server_default="", nullable=False),
        sa.Column("product", sa.String(length=128), server_default="", nullable=False),
        sa.Column("message", sa.Text(), server_default="", nullable=False),
        sa.Column("status", sa.String(length=16), server_default="new", nullable=False),
        sa.Column("score", sa.Integer(), server_default="0", nullable=False),
        sa.Column("qualification", sa.String(length=16), server_default="", nullable=False),
        sa.Column("reason", sa.String(length=255), server_default="", nullable=False),
        sa.Column("assigned_to", sa.String(length=128), server_default="", nullable=False),
        sa.Column("funnel", sa.String(length=16), server_default="", nullable=False),
        sa.Column("deal_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        schema="sales",
    )


def downgrade() -> None:
    op.drop_table("lead", schema="sales")
