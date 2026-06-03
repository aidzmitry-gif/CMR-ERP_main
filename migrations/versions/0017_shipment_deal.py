"""logistics: ссылка отгрузки на сделку (deal_id)

Revision ID: 0017
Revises: 0016
Create Date: 2026-06-03
"""
import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("shipment", sa.Column("deal_id", sa.Integer(), nullable=True), schema="logistics")


def downgrade() -> None:
    op.drop_column("shipment", "deal_id", schema="logistics")
