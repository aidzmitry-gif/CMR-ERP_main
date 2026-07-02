"""wms: план циклического пересчёта (cycle_count_plan)

``wms.cycle_count_plan`` — расписание периодической инвентаризации зоны/склада. ``run``
создаёт ``InventoryCount`` по складу плана, заполняет из 1С и сдвигает ``next_due_date``.

Revision ID: 0069
Revises: 0068
Create Date: 2026-06-28

Примечание: номер взят атомарно через scripts/next_migration.py (полоса «Склад/WMS»).
"""
import sqlalchemy as sa
from alembic import op

revision = "0069"
down_revision = "0068"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cycle_count_plan",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("warehouse", sa.String(128), server_default="Главный", nullable=False),
        sa.Column("zone", sa.String(64), nullable=True),
        sa.Column("cadence_days", sa.Integer(), server_default="30", nullable=False),
        sa.Column("next_due_date", sa.Date(), nullable=True),
        sa.Column("last_run_at", sa.DateTime(), nullable=True),
        sa.Column("active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("abc_class", sa.String(1), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cycle_count_plan")),
        schema="wms",
    )


def downgrade() -> None:
    op.drop_table("cycle_count_plan", schema="wms")
