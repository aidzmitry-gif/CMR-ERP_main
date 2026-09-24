"""Allow explicit MDM identity on procurement supplier profiles.

Existing profiles remain unlinked for human reconciliation; matching by name or
UNP during migration would silently assign an identity to historical data.
"""

import sqlalchemy as sa
from alembic import op

revision = "0179"
down_revision = "0178"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("supplier", sa.Column("counterparty_id", sa.Integer(), nullable=True), schema="procurement")
    op.create_foreign_key("fk_supplier_counterparty", "supplier", "counterparty", ["counterparty_id"], ["id"],
                          source_schema="procurement", ondelete="RESTRICT")
    op.create_unique_constraint("uq_supplier_counterparty", "supplier", ["counterparty_id"], schema="procurement")


def downgrade():
    op.drop_constraint("uq_supplier_counterparty", "supplier", schema="procurement", type_="unique")
    op.drop_constraint("fk_supplier_counterparty", "supplier", schema="procurement", type_="foreignkey")
    op.drop_column("supplier", "counterparty_id", schema="procurement")
