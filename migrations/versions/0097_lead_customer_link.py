"""leads: привязка лида к эталонному контрагенту + тип клиента (Цикл 10).

``counterparty_id`` — мягкая ссылка на golden record контрагента (public.counterparty),
как ``sku_id`` в позициях (без cross-schema FK). ``customer_kind`` — резолв входящего лида
против существующих клиентов: "" (новый/холодный) | "existing" (действующий клиент из MDM/1С)
| "regular" (постоянник — уже были лиды по этому контрагенту). Чтобы обращение действующего
клиента не выглядело холодным лидом и уходило приоритетно.

Revision ID: 0097
Revises: 0096
Create Date: 2026-07-11
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0097"
down_revision = "0096"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("lead", sa.Column("counterparty_id", sa.Integer(), nullable=True), schema="leads")
    op.add_column(
        "lead",
        sa.Column("customer_kind", sa.String(length=16), server_default="", nullable=False),
        schema="leads",
    )


def downgrade() -> None:
    op.drop_column("lead", "customer_kind", schema="leads")
    op.drop_column("lead", "counterparty_id", schema="leads")
