"""Add a stable optional Bitrix identity to deal tasks."""

import sqlalchemy as sa
from alembic import op

revision = "crm_live_deal_task_source_ref_01"
down_revision = "crm_live_timeline_attach_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "deal_task",
        sa.Column("source_ref", sa.String(128), nullable=True),
        schema="sales",
    )
    op.create_unique_constraint(
        "uq_deal_task_source_ref",
        "deal_task",
        ["source_ref"],
        schema="sales",
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_deal_task_source_ref",
        "deal_task",
        type_="unique",
        schema="sales",
    )
    op.drop_column("deal_task", "source_ref", schema="sales")
