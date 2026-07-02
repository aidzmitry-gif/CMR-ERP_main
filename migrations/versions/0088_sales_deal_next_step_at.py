"""sales: Deal.next_step_at — дата+время следующего шага (текст next_step остаётся описанием).

Открытый UX-хвост с круга 2 (ТЗ `_tz_sales_plan_fact_ui.md`, П4): `next_step` был просто
текстовым полем без даты, из-за чего группировка «По датам действий» (мокап
`sales-board-mockup.html`) нечестная. Добавляем ``next_step_at`` — nullable, существующие
сделки остаются валидны без бэкафилла.

Revision ID: 0088
Revises: 0087
Create Date: 2026-07-02

Примечание: номер взят атомарно через scripts/next_migration.py (полоса slice4-nextstep);
0087 при интеграции достался слайсу 3 (тендеры) — переномеровано в 0088 при слиянии.
"""
import sqlalchemy as sa
from alembic import op

revision = "0088"
down_revision = "0087"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "deal", sa.Column("next_step_at", sa.DateTime(), nullable=True), schema="sales"
    )


def downgrade() -> None:
    op.drop_column("deal", "next_step_at", schema="sales")
