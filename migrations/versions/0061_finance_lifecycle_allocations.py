"""finance: lifecycle платежа (due_date/paid_at/deal_id/counterparty_ref) + payment_allocation

Расширяет ``finance.payment`` плановыми/фактическими датами и провенансом сделки/контрагента
(MDM-ref); добавляет таблицу ``finance.payment_allocation`` для частичных поступлений.

Статус ``overdue`` НЕ хранится — вычисляется на чтении.

Revision ID: 0061
Revises: 0060
Create Date: 2026-06-28

Номер взят атомарно через scripts/next_migration.py (полоса «Финансы»).
"""
import sqlalchemy as sa
from alembic import op

revision = "0061"
down_revision = "0060"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) lifecycle колонки в finance.payment
    op.add_column("payment", sa.Column("due_date", sa.Date(), nullable=True), schema="finance")
    op.add_column("payment", sa.Column("paid_at", sa.DateTime(), nullable=True), schema="finance")
    op.add_column("payment", sa.Column("deal_id", sa.Integer(), nullable=True), schema="finance")
    op.add_column(
        "payment", sa.Column("counterparty_ref", sa.String(64), nullable=True), schema="finance"
    )

    # 2) частичные оплаты
    op.create_table(
        "payment_allocation",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("payment_id", sa.Integer(), nullable=False),
        sa.Column(
            "amount",
            sa.Numeric(14, 2),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "allocated_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["payment_id"],
            ["finance.payment.id"],
            ondelete="CASCADE",
            name="fk_payment_allocation_payment",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_payment_allocation"),
        schema="finance",
    )
    op.create_index(
        "ix_payment_allocation_payment_id",
        "payment_allocation",
        ["payment_id"],
        schema="finance",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_payment_allocation_payment_id", table_name="payment_allocation", schema="finance"
    )
    op.drop_table("payment_allocation", schema="finance")
    op.drop_column("payment", "counterparty_ref", schema="finance")
    op.drop_column("payment", "deal_id", schema="finance")
    op.drop_column("payment", "paid_at", schema="finance")
    op.drop_column("payment", "due_date", schema="finance")
