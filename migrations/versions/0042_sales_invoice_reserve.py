"""sales: SALES-51 — резерв под счёт + срок действия (поля deal_document)

Срез 2 жизненного цикла резерва: ``reserve_status`` (none→reserved→consumed|released),
``valid_until`` (срок счёта = +AIOS_INVOICE_VALID_DAYS дн.), отметки времени для
идемпотентного фонового шага ``tick_invoice_reserve`` (напоминание/аннулирование).

Revision ID: 0042
Revises: 0041
Create Date: 2026-06-24
"""
import sqlalchemy as sa
from alembic import op

revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("deal_document", sa.Column("valid_until", sa.Date(), nullable=True), schema="sales")
    op.add_column(
        "deal_document",
        sa.Column("reserve_status", sa.String(length=16), server_default="none", nullable=False),
        schema="sales",
    )
    op.add_column("deal_document", sa.Column("reserved_at", sa.DateTime(), nullable=True), schema="sales")
    op.add_column("deal_document", sa.Column("reminded_at", sa.DateTime(), nullable=True), schema="sales")
    op.add_column("deal_document", sa.Column("cancelled_at", sa.DateTime(), nullable=True), schema="sales")


def downgrade() -> None:
    for col in ("cancelled_at", "reminded_at", "reserved_at", "reserve_status", "valid_until"):
        op.drop_column("deal_document", col, schema="sales")
