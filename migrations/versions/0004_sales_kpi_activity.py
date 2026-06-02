"""sales: цели KPI и активности (План/Факт)

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-02
"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "kpi_target",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=128), nullable=False),
        sa.Column("target", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("unit", sa.String(length=16), server_default="count", nullable=False),
        sa.Column("icon", sa.String(length=16), nullable=False),
        sa.Column("tone", sa.String(length=16), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.UniqueConstraint("key", name=op.f("uq_kpi_target_key")),
        schema="sales",
    )
    op.create_table(
        "activity",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kpi_key", sa.String(length=32), nullable=False),
        sa.Column("owner", sa.String(length=128), server_default="", nullable=False),
        sa.Column("value", sa.Numeric(precision=14, scale=2), server_default="1", nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        schema="sales",
    )


def downgrade() -> None:
    op.drop_table("activity", schema="sales")
    op.drop_table("kpi_target", schema="sales")
