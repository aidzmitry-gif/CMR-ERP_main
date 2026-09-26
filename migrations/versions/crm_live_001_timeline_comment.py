"""Keep CRM timeline comments with their exact deal or lead owner.

The source identity is nullable for local comments. Binary attachments remain
outside this revision and must be reconciled before a full source load.
"""

import sqlalchemy as sa
from alembic import op

revision = "crm_live_timeline_01"
down_revision = "crm_live_stage_hist_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "crm_timeline_comment",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("entity_type", sa.String(16), nullable=False),
        sa.Column("deal_id", sa.Integer(), sa.ForeignKey("sales.deal.id"), nullable=True),
        sa.Column("lead_id", sa.Integer(), sa.ForeignKey("leads.lead.id"), nullable=True),
        sa.Column("source_ref", sa.String(128), nullable=True),
        sa.Column("source_entity_id", sa.String(64), nullable=True),
        sa.Column("author_source_id", sa.String(64), nullable=True),
        sa.Column("author_display", sa.String(128), server_default="", nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("source_ref", name="uq_crm_timeline_comment_source_ref"),
        sa.CheckConstraint(
            "(entity_type = 'deal' AND deal_id IS NOT NULL AND lead_id IS NULL) "
            "OR (entity_type = 'lead' AND lead_id IS NOT NULL AND deal_id IS NULL)",
            name="crm_timeline_comment_owner",
        ),
        schema="sales",
    )
    op.create_index(
        "ix_crm_timeline_comment_deal_time",
        "crm_timeline_comment",
        ["deal_id", "created_at"],
        schema="sales",
    )
    op.create_index(
        "ix_crm_timeline_comment_lead_time",
        "crm_timeline_comment",
        ["lead_id", "created_at"],
        schema="sales",
    )


def downgrade() -> None:
    op.drop_index("ix_crm_timeline_comment_lead_time", table_name="crm_timeline_comment", schema="sales")
    op.drop_index("ix_crm_timeline_comment_deal_time", table_name="crm_timeline_comment", schema="sales")
    op.drop_table("crm_timeline_comment", schema="sales")
