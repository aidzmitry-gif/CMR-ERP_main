"""sales: документы сделки (счёт/договор/заказ) и запись в 1С

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-02
"""
import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "deal_document",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("deal_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("number", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="draft", nullable=False),
        sa.Column("onec_ref", sa.String(length=64), nullable=True),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("posted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["deal_id"], ["sales.deal.id"], name=op.f("fk_deal_document_deal_id_deal")
        ),
        schema="sales",
    )


def downgrade() -> None:
    op.drop_table("deal_document", schema="sales")
