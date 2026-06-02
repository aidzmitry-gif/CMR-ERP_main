"""core: неизменяемый журнал аудита

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-02
"""
import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ts", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("actor", sa.String(length=128), server_default="", nullable=False),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("entity_ref", sa.String(length=64), server_default="", nullable=False),
        sa.Column("detail", sa.JSON(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("audit_log")
