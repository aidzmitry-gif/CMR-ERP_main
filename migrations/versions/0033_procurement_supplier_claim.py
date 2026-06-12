"""procurement: претензии поставщикам (supplier_claim)

Одна новая таблица схемы ``procurement``:
- ``supplier_claim`` — претензия поставщику; создаётся автоматически при браке в
  производстве (событие ``production.scrap``), замыкает цикл ОТК → закупки.

Revision ID: 0033
Revises: 0032
Create Date: 2026-06-12
"""
import sqlalchemy as sa
from alembic import op

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "supplier_claim",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("supplier", sa.String(length=255), server_default="", nullable=False),
        sa.Column("item", sa.String(length=255), server_default="", nullable=False),
        sa.Column("reason", sa.String(length=400), server_default="", nullable=False),
        sa.Column("order_code", sa.String(length=64), server_default="", nullable=False),
        sa.Column("status", sa.String(length=32), server_default="open", nullable=False),
        sa.Column("source", sa.String(length=32), server_default="production", nullable=False),
        sa.Column("entity_ref", sa.String(length=128), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        schema="procurement",
    )


def downgrade() -> None:
    op.drop_table("supplier_claim", schema="procurement")
