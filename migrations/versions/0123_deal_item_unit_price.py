"""sales: confirmed unit price belongs to a deal line.

Revision 0123 was reserved after the operator delegated number selection.
Existing lines deliberately remain unpriced until their price is confirmed.
"""

import sqlalchemy as sa
from alembic import op

revision = "0123"
down_revision = "0116"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("deal_item", sa.Column("unit_price", sa.Numeric(14, 2), nullable=True), schema="sales")
    op.create_check_constraint(
        op.f("ck_deal_item_unit_price_nonnegative"), "deal_item", "unit_price >= 0", schema="sales",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_deal_item_unit_price_nonnegative"), "deal_item", schema="sales", type_="check")
    op.drop_column("deal_item", "unit_price", schema="sales")
