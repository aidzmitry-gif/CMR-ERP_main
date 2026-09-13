"""Stable sales party references; never rewrite legacy text or document originals."""
import sqlalchemy as sa
from alembic import op

revision = "0118"
down_revision = "0117"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("deal", sa.Column("counterparty_id", sa.Integer(), nullable=True), schema="sales")
    op.add_column("deal", sa.Column("branch_id", sa.Integer(), nullable=True), schema="sales")
    op.create_index("ix_sales_deal_counterparty_id", "deal", ["counterparty_id"], schema="sales")
    op.create_index("ix_sales_deal_branch_id", "deal", ["branch_id"], schema="sales")
    # Only an exact globally unique legacy name can supply an initial identity.
    # Archived, duplicate, ambiguous and absent records remain explicitly unresolved.
    op.execute("""
        UPDATE sales.deal SET counterparty_id = (
            SELECT c.id FROM counterparty c
            WHERE c.name = sales.deal.counterparty AND c.is_active = true
              AND c.merged_into_id IS NULL
        ) WHERE counterparty <> '' AND (
            SELECT count(*) FROM counterparty c WHERE c.name = sales.deal.counterparty
        ) = 1
    """)


def downgrade() -> None:
    # The untouched backfill can be reversed. An explicit selection or later rename
    # that cannot be recovered from the old schema requires a preserved backup.
    changed = op.get_bind().execute(sa.text("""
        SELECT count(*) FROM sales.deal d
        WHERE d.branch_id IS NOT NULL OR (d.counterparty_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM counterparty c WHERE c.id = d.counterparty_id
              AND c.name = d.counterparty AND c.is_active = true AND c.merged_into_id IS NULL
              AND (SELECT count(*) FROM counterparty x WHERE x.name = d.counterparty) = 1
        ))
    """)).scalar()
    if changed:
        raise RuntimeError("0118 downgrade would discard party identity; preserve a verified backup")
    op.drop_index("ix_sales_deal_branch_id", table_name="deal", schema="sales")
    op.drop_index("ix_sales_deal_counterparty_id", table_name="deal", schema="sales")
    op.drop_column("deal", "branch_id", schema="sales")
    op.drop_column("deal", "counterparty_id", schema="sales")
