"""procurement: план сбора машины — transport_method + po.target_arrival + milestones

- ``procurement.transport_method`` — справочник способов перевозки (шаблон длительностей этапов,
  JSON {stage: дни}); дефолты (Контейнер/Машина) сидятся лениво кодом (plan.DEFAULT_METHODS).
- ``purchase_order`` += ``transport_method_code`` (soft-ref) + ``target_arrival_date`` («В Минске до»).
- ``procurement.purchase_order_milestone`` — вехи графика сбора: этап + план/факт даты (обратный
  waterfall от target_arrival), длительность правится на машине. UNIQUE (order_id, stage).

Аддитивна (старые строки не ломаются). Одна ревизия.

Revision ID: 0072
Revises: 0071
Create Date: 2026-06-28

Примечание: номер взят атомарно scripts/next_migration.py (procurement); down_revision — реальный head.
"""
import sqlalchemy as sa
from alembic import op

revision = "0072"
down_revision = "0071"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "transport_method",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("durations", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_transport_method")),
        sa.UniqueConstraint("code", name=op.f("uq_transport_method_code")),
        schema="procurement",
    )

    op.add_column(
        "purchase_order",
        sa.Column("transport_method_code", sa.String(32), nullable=True),
        schema="procurement",
    )
    op.add_column(
        "purchase_order",
        sa.Column("target_arrival_date", sa.Date(), nullable=True),
        schema="procurement",
    )

    op.create_table(
        "purchase_order_milestone",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("seq", sa.Integer(), server_default="0", nullable=False),
        sa.Column("duration_days", sa.Integer(), server_default="0", nullable=False),
        sa.Column("planned_date", sa.Date(), nullable=True),
        sa.Column("actual_date", sa.Date(), nullable=True),
        sa.ForeignKeyConstraint(
            ["order_id"], ["procurement.purchase_order.id"],
            name=op.f("fk_purchase_order_milestone_order_id_purchase_order"), ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_purchase_order_milestone")),
        sa.UniqueConstraint("order_id", "stage", name=op.f("uq_purchase_order_milestone_order_id")),
        schema="procurement",
    )
    op.create_index(
        "ix_purchase_order_milestone_order", "purchase_order_milestone", ["order_id"],
        schema="procurement",
    )


def downgrade() -> None:
    op.drop_index("ix_purchase_order_milestone_order", "purchase_order_milestone", schema="procurement")
    op.drop_table("purchase_order_milestone", schema="procurement")
    op.drop_column("purchase_order", "target_arrival_date", schema="procurement")
    op.drop_column("purchase_order", "transport_method_code", schema="procurement")
    op.drop_table("transport_method", schema="procurement")
