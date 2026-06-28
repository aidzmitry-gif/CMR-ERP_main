"""finance: cost_center + мультивалюта (currency + amount_orig)

Расширяет ``finance.payment`` колонкой ``cost_center`` (центр затрат, свободная строка
из захардкоженного справочника), ``currency`` (default ``BYN``) и ``amount_orig`` (сумма
в исходной валюте до конвертации в BYN с FX-буфером).

Revision ID: 0063
Revises: 0062
Create Date: 2026-06-28

Номер взят атомарно через scripts/next_migration.py (полоса «Финансы»).
"""
import sqlalchemy as sa
from alembic import op

revision = "0063"
down_revision = "0062"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "payment", sa.Column("cost_center", sa.String(32), nullable=True), schema="finance"
    )
    op.add_column(
        "payment",
        sa.Column("currency", sa.String(3), server_default="BYN", nullable=False),
        schema="finance",
    )
    op.add_column(
        "payment", sa.Column("amount_orig", sa.Numeric(14, 2), nullable=True), schema="finance"
    )


def downgrade() -> None:
    op.drop_column("payment", "amount_orig", schema="finance")
    op.drop_column("payment", "currency", schema="finance")
    op.drop_column("payment", "cost_center", schema="finance")
