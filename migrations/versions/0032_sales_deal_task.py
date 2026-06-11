"""sales: задачи по сделке (SALES-41)

Revision ID: 0032
Revises: 0031
Create Date: 2026-06-12
"""
import sqlalchemy as sa
from alembic import op

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "deal_task",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("deal_id", sa.Integer(), sa.ForeignKey("sales.deal.id"), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=16), server_default="other", nullable=False),
        sa.Column("assignee_id", sa.Integer(), nullable=True),
        sa.Column("due_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="open", nullable=False),
        sa.Column("result", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("done_at", sa.DateTime(), nullable=True),
        schema="sales",
    )


def downgrade() -> None:
    op.drop_table("deal_task", schema="sales")
