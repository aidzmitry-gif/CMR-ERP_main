"""production: план производства (production_plan) + дата завершения наряда

- ``production.production_plan`` — план по месяцам (длинный формат: год × изделие × месяц).
  Норма н.ч/шт и факт здесь НЕ хранятся (норма — из справочника, факт — из нарядов).
- ``production.production_order.completed_at`` — дата перехода наряда в ``done``;
  по ней факт раскладывается по месяцам (план/факт, аналитика).

Revision ID: 0036
Revises: 0035
Create Date: 2026-06-12

Примечание: занумерована 0036 (а не 0034), т.к. параллельная sales-сессия заняла
0034/0035 (loss_reasons_v2, plan_target). Чейн линейный: 0035 → 0036.
"""
import sqlalchemy as sa
from alembic import op

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "production_order",
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        schema="production",
    )
    op.create_table(
        "production_plan",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("year", sa.Integer(), nullable=False, index=True),
        sa.Column("product", sa.String(length=255), nullable=False),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column("plan_qty", sa.Integer(), server_default="0", nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("year", "product", "month", name="uq_production_plan_cell"),
        schema="production",
    )


def downgrade() -> None:
    op.drop_table("production_plan", schema="production")
    op.drop_column("production_order", "completed_at", schema="production")
