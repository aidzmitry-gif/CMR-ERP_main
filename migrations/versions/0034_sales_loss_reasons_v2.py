"""sales: SALES-40 — +territory/+liquidated в loss_reason; SALES-47 — Activity.owner_id

Revision ID: 0034
Revises: 0033
Create Date: 2026-06-12
"""
import sqlalchemy as sa
from alembic import op

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SALES-40: добавить две причины отказа от заказчика (§0.1 ТЗ Сделки 2.0)
    loss_reason = sa.table(
        "loss_reason",
        sa.column("code", sa.String),
        sa.column("title", sa.String),
        sa.column("sort_order", sa.Integer),
        sa.column("active", sa.Boolean),
        schema="sales",
    )
    op.bulk_insert(
        loss_reason,
        [
            {
                "code": "territory",
                "title": "Не подходим по территории",
                "sort_order": 8,
                "active": True,
            },
            {
                "code": "liquidated",
                "title": "Контрагент ликвидирован / не работает",
                "sort_order": 9,
                "active": True,
            },
        ],
    )

    # SALES-47: факт активности — мягкая ссылка на hr.employee (чей факт)
    op.add_column(
        "activity",
        sa.Column("owner_id", sa.Integer(), nullable=True),
        schema="sales",
    )


def downgrade() -> None:
    op.drop_column("activity", "owner_id", schema="sales")
    # Удалить только добавленные записи (по коду, чтобы не задеть другие)
    op.execute(
        "DELETE FROM sales.loss_reason WHERE code IN ('territory', 'liquidated')"
    )
