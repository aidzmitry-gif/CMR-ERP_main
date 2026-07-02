"""marketing/sales: SEO Phase B–D (seo_task, campaign UTM, lead attribution)

Revision ID: 0082
Revises: 0081
Create Date: 2026-07-01
"""
import sqlalchemy as sa
from alembic import op

revision = "0082"
down_revision = "0081"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "seo_task",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("seo_project_id", sa.Integer(), sa.ForeignKey("marketing.seo_project.id"), nullable=False),
        sa.Column("external_task_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("type", sa.String(length=32), server_default="", nullable=False),
        sa.Column("priority", sa.String(length=16), server_default="medium", nullable=False),
        sa.Column("status", sa.String(length=32), server_default="new", nullable=False),
        sa.Column("url", sa.String(length=512), server_default="", nullable=False),
        sa.Column("cluster_name", sa.String(length=255), server_default="", nullable=False),
        sa.Column("assigned_to", sa.String(length=128), server_default="", nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("external_task_id", name="uq_seo_task_external_task_id"),
        schema="marketing",
    )
    op.create_index("ix_seo_task_project_priority", "seo_task", ["seo_project_id", "priority"], schema="marketing")

    op.add_column("campaign", sa.Column("utm_source", sa.String(length=128), server_default="", nullable=False), schema="marketing")
    op.add_column("campaign", sa.Column("utm_medium", sa.String(length=128), server_default="", nullable=False), schema="marketing")
    op.add_column("campaign", sa.Column("utm_campaign", sa.String(length=255), server_default="", nullable=False), schema="marketing")
    op.add_column("campaign", sa.Column("goal", sa.String(length=255), server_default="", nullable=False), schema="marketing")
    op.add_column("campaign", sa.Column("kpi_json", sa.JSON(), nullable=True), schema="marketing")

    op.add_column("lead", sa.Column("utm_source", sa.String(length=128), server_default="", nullable=False), schema="sales")
    op.add_column("lead", sa.Column("utm_medium", sa.String(length=128), server_default="", nullable=False), schema="sales")
    op.add_column("lead", sa.Column("utm_campaign", sa.String(length=255), server_default="", nullable=False), schema="sales")
    op.add_column("lead", sa.Column("landing_url", sa.String(length=512), server_default="", nullable=False), schema="sales")


def downgrade() -> None:
    op.drop_column("lead", "landing_url", schema="sales")
    op.drop_column("lead", "utm_campaign", schema="sales")
    op.drop_column("lead", "utm_medium", schema="sales")
    op.drop_column("lead", "utm_source", schema="sales")
    op.drop_column("campaign", "kpi_json", schema="marketing")
    op.drop_column("campaign", "goal", schema="marketing")
    op.drop_column("campaign", "utm_campaign", schema="marketing")
    op.drop_column("campaign", "utm_medium", schema="marketing")
    op.drop_column("campaign", "utm_source", schema="marketing")
    op.drop_index("ix_seo_task_project_priority", table_name="seo_task", schema="marketing")
    op.drop_table("seo_task", schema="marketing")
