"""sales: позиции номенклатуры сделки (deal_item → SKU)

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-02
"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "deal_item",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("deal_id", sa.Integer(), nullable=False),
        sa.Column("sku_id", sa.Integer(), nullable=False),
        sa.Column("qty", sa.Numeric(precision=14, scale=2), server_default="1", nullable=False),
        sa.ForeignKeyConstraint(
            ["deal_id"], ["sales.deal.id"], name=op.f("fk_deal_item_deal_id_deal")
        ),
        schema="sales",
    )


def downgrade() -> None:
    op.drop_table("deal_item", schema="sales")
