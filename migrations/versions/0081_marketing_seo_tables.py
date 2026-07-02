"""marketing: SEO registry tables (Phase A)

Схема ``marketing.site``, ``marketing.seo_project``, ``marketing.seo_snapshot``
для интеграции с SEO/GEO Growth Platform (MAR-8).

Revision ID: 0081
Revises: 0080
Create Date: 2026-07-01
"""
import sqlalchemy as sa
from alembic import op

revision = "0081"
down_revision = "0080"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "site",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("counterparty_id", sa.Integer(), sa.ForeignKey("counterparty.id"), nullable=True),
        sa.Column("domain", sa.String(length=255), nullable=False),
        sa.Column("region", sa.String(length=64), server_default="", nullable=False),
        sa.Column("is_primary", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("domain", name="uq_site_domain"),
        schema="marketing",
    )
    op.create_table(
        "seo_project",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("site_id", sa.Integer(), sa.ForeignKey("marketing.site.id"), nullable=True),
        sa.Column("campaign_id", sa.Integer(), sa.ForeignKey("marketing.campaign.id"), nullable=True),
        sa.Column("external_project_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="active", nullable=False),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("external_project_id", name="uq_seo_project_external_project_id"),
        schema="marketing",
    )
    op.create_index(
        "ix_seo_project_external_project_id",
        "seo_project",
        ["external_project_id"],
        schema="marketing",
    )
    op.create_table(
        "seo_snapshot",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("seo_project_id", sa.Integer(), sa.ForeignKey("marketing.seo_project.id"), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("visibility", sa.Numeric(precision=8, scale=2), server_default="0", nullable=False),
        sa.Column("total_keywords", sa.Integer(), server_default="0", nullable=False),
        sa.Column("top10_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("critical_tasks", sa.Integer(), server_default="0", nullable=False),
        sa.Column("quick_wins", sa.Integer(), server_default="0", nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        schema="marketing",
    )
    op.create_index(
        "ix_seo_snapshot_project_date",
        "seo_snapshot",
        ["seo_project_id", "snapshot_date"],
        schema="marketing",
    )


def downgrade() -> None:
    op.drop_index("ix_seo_snapshot_project_date", table_name="seo_snapshot", schema="marketing")
    op.drop_table("seo_snapshot", schema="marketing")
    op.drop_index("ix_seo_project_external_project_id", table_name="seo_project", schema="marketing")
    op.drop_table("seo_project", schema="marketing")
    op.drop_table("site", schema="marketing")
