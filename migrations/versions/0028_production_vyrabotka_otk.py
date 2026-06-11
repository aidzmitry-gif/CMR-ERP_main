"""production: выработка (табель + ЗП) и ОТК (решения, претензия в закупки)

Две новые таблицы схемы ``production``:
- ``production_worker`` — табель сборщиков (оклад, дни, выработка н.ч);
  ЗП = оклад × дни / 22 + выработка × премиальная ставка.
- ``production_qc`` — журнал решений ОТК (accept | rework | scrap);
  брак публикует ``production.scrap`` → претензия в закупки.

Revision ID: 0028
Revises: 0027
Create Date: 2026-06-11
"""
import sqlalchemy as sa
from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "production_worker",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("salary", sa.Float(), server_default="0", nullable=False),
        sa.Column("days_worked", sa.Integer(), server_default="0", nullable=False),
        sa.Column("nh_output", sa.Float(), server_default="0", nullable=False),
        schema="production",
    )
    op.create_table(
        "production_qc",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_code", sa.String(length=64), server_default="", nullable=False),
        sa.Column("product", sa.String(length=255), server_default="", nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.String(length=255), server_default="", nullable=False),
        sa.Column("inspector", sa.String(length=128), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        schema="production",
    )


def downgrade() -> None:
    op.drop_table("production_qc", schema="production")
    op.drop_table("production_worker", schema="production")
