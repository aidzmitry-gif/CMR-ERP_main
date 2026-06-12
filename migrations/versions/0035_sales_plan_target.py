"""sales: личный план продаж (SALES-47) — таблица plan_target

Revision ID: 0035
Revises: 0034
Create Date: 2026-06-12
"""
import sqlalchemy as sa
from alembic import op

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "plan_target",
        sa.Column("id", sa.Integer(), primary_key=True),
        # owner_id: мягкая ссылка на hr.employee (без cross-schema FK)
        sa.Column("owner_id", sa.Integer(), nullable=False),
        # metric: ключ показателя (calls, cold_calls, leads, won_amount, …)
        sa.Column("metric", sa.String(length=32), nullable=False),
        # period_type: day | week | month | quarter | year
        sa.Column("period_type", sa.String(length=8), nullable=False),
        # period_key: 2026-06-12 | 2026-W24 | 2026-06 | 2026-Q2 | 2026
        sa.Column("period_key", sa.String(length=10), nullable=False),
        # target: цель в BYN (денежные) или шт (счётные)
        sa.Column("target", sa.Numeric(14, 2), nullable=False),
        # status: draft → pending_approval → approved / rejected
        sa.Column("status", sa.String(length=16), server_default="draft", nullable=False),
        sa.Column("approved_by", sa.String(length=128), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint(
            "owner_id", "metric", "period_type", "period_key",
            name="uq_plan_target",
        ),
        schema="sales",
    )


def downgrade() -> None:
    op.drop_table("plan_target", schema="sales")
