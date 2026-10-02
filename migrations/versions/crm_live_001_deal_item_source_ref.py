"""Preserve source identity for imported CRM deal lines.

Existing manual lines keep a NULL source_ref; only imported source keys are unique.
This local candidate follows 0129. Recheck Alembic heads after accounting integration.
"""

import sqlalchemy as sa
from alembic import op

revision = "crm_live_item_src_01"
down_revision = "0129"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("deal_item", sa.Column("source_ref", sa.String(128), nullable=True), schema="sales")
    op.create_unique_constraint("uq_deal_item_source_ref", "deal_item", ["source_ref"], schema="sales")


def downgrade() -> None:
    op.drop_constraint("uq_deal_item_source_ref", "deal_item", schema="sales", type_="unique")
    op.drop_column("deal_item", "source_ref", schema="sales")
