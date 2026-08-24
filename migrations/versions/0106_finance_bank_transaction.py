"""finance: ledger банковских зачислений — finance.bank_transaction (оплата от клиента, Альфа)

Сырое входящее зачисление из банка (Альфа host-to-host). ``ext_id`` UNIQUE — идемпотентность
опроса (повторный sync не задваивает оплату клиента, PLATFORM #1). Матчер (bank_ingest)
связывает зачисление с открытым ``receivable`` по назначению+УНП и проводит поступление;
несматченное остаётся в очереди ``match_status='unmatched'`` («разобрать вручную»).

Аддитивно: новая таблица + два nullable FK на ``finance.payment``/``payment_allocation``
(ON DELETE SET NULL — удаление платежа не рушит след зачисления). Обратимо (drop_table).

Revision ID: 0106
Revises: 0105
Create Date: 2026-07-19
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0106"
down_revision = "0105"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bank_transaction",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ext_id", sa.String(length=128), nullable=False),
        sa.Column("occurred_on", sa.Date(), nullable=True),
        sa.Column("amount", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="BYN", nullable=False),
        sa.Column("payer_unp", sa.String(length=32), nullable=True),
        sa.Column("payer_name", sa.String(length=255), nullable=True),
        sa.Column("purpose", sa.String(length=512), nullable=True),
        sa.Column("account_code", sa.String(length=64), nullable=True),
        sa.Column(
            "match_status", sa.String(length=16), server_default="unmatched", nullable=False
        ),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.Column("payment_id", sa.Integer(), nullable=True),
        sa.Column("allocation_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["payment_id"], ["finance.payment.id"],
            name=op.f("fk_bank_transaction_payment_id_payment"), ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["allocation_id"], ["finance.payment_allocation.id"],
            name=op.f("fk_bank_transaction_allocation_id_payment_allocation"), ondelete="SET NULL",
        ),
        sa.UniqueConstraint("ext_id", name=op.f("uq_bank_transaction_ext_id")),
        schema="finance",
    )
    op.create_index(
        op.f("ix_finance_bank_transaction_match_status"),
        "bank_transaction", ["match_status"], schema="finance",
    )
    op.create_index(
        op.f("ix_finance_bank_transaction_payment_id"),
        "bank_transaction", ["payment_id"], schema="finance",
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_finance_bank_transaction_payment_id"), "bank_transaction", schema="finance"
    )
    op.drop_index(
        op.f("ix_finance_bank_transaction_match_status"), "bank_transaction", schema="finance"
    )
    op.drop_table("bank_transaction", schema="finance")
