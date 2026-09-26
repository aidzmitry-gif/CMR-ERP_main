"""Preserve Bitrix source identity for imported deal stage history.

Local events remain source_ref=NULL. Recheck the Alembic chain after accounting
integration and rehearse this schema change on a restored production copy.
"""

import sqlalchemy as sa
from alembic import op

revision = "crm_live_stage_hist_01"
down_revision = "crm_live_item_src_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "deal_stage_event",
        sa.Column("source_ref", sa.String(128), nullable=True),
        schema="sales",
    )
    op.add_column(
        "deal_stage_event",
        sa.Column("source_stage_id", sa.String(128), nullable=True),
        schema="sales",
    )
    op.add_column(
        "deal_stage_event",
        sa.Column("source_category_id", sa.String(32), nullable=True),
        schema="sales",
    )
    op.add_column(
        "deal_stage_event",
        sa.Column("source_type_id", sa.Integer(), nullable=True),
        schema="sales",
    )
    op.add_column(
        "deal_stage_event",
        sa.Column("source_semantic_id", sa.String(8), nullable=True),
        schema="sales",
    )
    op.create_unique_constraint(
        "uq_deal_stage_event_source_ref",
        "deal_stage_event",
        ["source_ref"],
        schema="sales",
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_deal_stage_event_source_ref",
        "deal_stage_event",
        schema="sales",
        type_="unique",
    )
    op.drop_column("deal_stage_event", "source_semantic_id", schema="sales")
    op.drop_column("deal_stage_event", "source_type_id", schema="sales")
    op.drop_column("deal_stage_event", "source_category_id", schema="sales")
    op.drop_column("deal_stage_event", "source_stage_id", schema="sales")
    op.drop_column("deal_stage_event", "source_ref", schema="sales")
