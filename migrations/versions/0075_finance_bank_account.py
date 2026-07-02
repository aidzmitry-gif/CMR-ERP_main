"""finance: bank_account + Payment.account_id (Р4 — Платёжный календарь)

Создаёт справочник банковских счетов/касс (``finance.bank_account``) и добавляет колонку
``account_id`` в ``finance.payment`` для разнесения движений по счетам. ``account_id``
nullable=True — старые платежи остаются «без счёта» (= общий кэш), без backfill. FK
``ON DELETE SET NULL`` — закрытие счёта не теряет историю платежей.

Revision ID: 0075
Revises: 0074
Create Date: 2026-06-28

Номер взят атомарно через scripts/next_migration.py (полоса «Финансы»).
"""
import sqlalchemy as sa
from alembic import op

revision = "0075"
down_revision = "0074"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bank_account",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("currency", sa.String(3), server_default="BYN", nullable=False),
        sa.Column(
            "opening_balance", sa.Numeric(14, 2), server_default="0", nullable=False
        ),
        sa.Column("opening_at", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("code", name="uq_bank_account_code"),
        schema="finance",
    )
    op.add_column(
        "payment",
        sa.Column("account_id", sa.Integer(), nullable=True),
        schema="finance",
    )
    op.create_foreign_key(
        "fk_payment_account_id_bank_account",
        "payment",
        "bank_account",
        ["account_id"],
        ["id"],
        ondelete="SET NULL",
        source_schema="finance",
        referent_schema="finance",
    )
    op.create_index(
        "ix_payment_account_id", "payment", ["account_id"], schema="finance"
    )


def downgrade() -> None:
    op.drop_index("ix_payment_account_id", table_name="payment", schema="finance")
    op.drop_constraint(
        "fk_payment_account_id_bank_account", "payment", type_="foreignkey", schema="finance"
    )
    op.drop_column("payment", "account_id", schema="finance")
    op.drop_table("bank_account", schema="finance")
