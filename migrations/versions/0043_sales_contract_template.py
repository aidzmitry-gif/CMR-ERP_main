"""sales: шаблоны договора + поля условий на документе (SALES-53)

Часть C ТЗ «Окно звонка и резерв»: договор по шаблону с авто-реквизитами по УНП.
- Новая таблица ``sales.contract_template`` (тело с плейсхолдерами ``{{...}}``).
- На ``sales.deal_document`` (для kind=contract) добавляются условия:
  ``template_id`` (мягкая ссылка на шаблон), ``payment_terms``, ``delivery_terms``,
  ``terms_json`` (прочие согласованные условия + реквизиты покупателя по УНП —
  чтобы не править shared-схему Counterparty).

Revision ID: 0043
Revises: 0042
Create Date: 2026-06-24

Примечание: чейн линейный 0042 → 0043. Если параллельная сессия уже заняла 0043 —
перенумеровать (как было с 0034/0036).
"""
import sqlalchemy as sa
from alembic import op

revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "contract_template",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("code", name="uq_contract_template_code"),
        schema="sales",
    )
    op.add_column(
        "deal_document",
        sa.Column("template_id", sa.Integer(), nullable=True),
        schema="sales",
    )
    op.add_column(
        "deal_document",
        sa.Column("payment_terms", sa.String(length=255), nullable=True),
        schema="sales",
    )
    op.add_column(
        "deal_document",
        sa.Column("delivery_terms", sa.String(length=255), nullable=True),
        schema="sales",
    )
    op.add_column(
        "deal_document",
        sa.Column("terms_json", sa.JSON(), nullable=True),
        schema="sales",
    )


def downgrade() -> None:
    for col in ("terms_json", "delivery_terms", "payment_terms", "template_id"):
        op.drop_column("deal_document", col, schema="sales")
    op.drop_table("contract_template", schema="sales")
