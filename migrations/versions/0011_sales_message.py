"""sales: сообщения по сделке (омниканальная переписка)

Revision ID: 0011
Revises: 0010
Create Date: 2026-06-03
"""
import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "message",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("deal_id", sa.Integer(), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("direction", sa.String(length=8), server_default="out", nullable=False),
        sa.Column("author", sa.String(length=128), server_default="", nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["deal_id"], ["sales.deal.id"], name=op.f("fk_message_deal_id_deal")
        ),
        schema="sales",
    )


def downgrade() -> None:
    op.drop_table("message", schema="sales")
