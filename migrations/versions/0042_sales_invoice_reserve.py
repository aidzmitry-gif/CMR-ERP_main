"""sales: резерв под счёт + срок действия счёта (SALES-51)

Срез 1: счёт (invoice), как и заказ, резервирует складские остатки. На документе
появляется жизненный цикл резерва и срок действия счёта (5 дней по счёт-протоколу):
``valid_until`` (created + AIOS_INVOICE_VALID_DAYS дней), ``reserve_status``
(none → reserved → consumed | released) и метки времени резерва/напоминания/аннулирования.

Revision ID: 0042
Revises: 0041
Create Date: 2026-06-23

Примечание: чейн линейный 0041 → 0042. Если параллельная сессия уже заняла 0042 —
перенумеровать (как было с 0034/0036).
"""
import sqlalchemy as sa
from alembic import op

revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "deal_document",
        sa.Column("valid_until", sa.Date(), nullable=True),
        schema="sales",
    )
    op.add_column(
        "deal_document",
        sa.Column("reserve_status", sa.String(length=16), server_default="none", nullable=False),
        schema="sales",
    )
    op.add_column(
        "deal_document",
        sa.Column("reserved_at", sa.DateTime(), nullable=True),
        schema="sales",
    )
    op.add_column(
        "deal_document",
        sa.Column("reminded_at", sa.DateTime(), nullable=True),
        schema="sales",
    )
    op.add_column(
        "deal_document",
        sa.Column("cancelled_at", sa.DateTime(), nullable=True),
        schema="sales",
    )


def downgrade() -> None:
    for col in ("cancelled_at", "reminded_at", "reserved_at", "reserve_status", "valid_until"):
        op.drop_column("deal_document", col, schema="sales")
