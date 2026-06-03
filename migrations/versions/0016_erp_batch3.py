"""erp: модули Сервис / HR

Revision ID: 0016
Revises: 0015
Create Date: 2026-06-03
"""
import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS service")
    op.create_table(
        "ticket",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("customer", sa.String(length=255), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), server_default="", nullable=False),
        sa.Column("status", sa.String(length=32), server_default="open", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        schema="service",
    )

    op.execute("CREATE SCHEMA IF NOT EXISTS hr")
    op.create_table(
        "employee",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("position", sa.String(length=128), server_default="", nullable=False),
        sa.Column("department", sa.String(length=128), server_default="", nullable=False),
        sa.Column("status", sa.String(length=32), server_default="active", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        schema="hr",
    )


def downgrade() -> None:
    op.drop_table("employee", schema="hr")
    op.execute("DROP SCHEMA IF EXISTS hr")
    op.drop_table("ticket", schema="service")
    op.execute("DROP SCHEMA IF EXISTS service")
