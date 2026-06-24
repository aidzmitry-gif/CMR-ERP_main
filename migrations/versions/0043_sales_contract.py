"""sales: SALES-53 — шаблоны договора + согласованные условия

Новая таблица ``sales.contract_template`` (шаблон с плейсхолдерами ``{{...}}``) и поля
договора на ``deal_document``: ссылка на шаблон + условия оплаты/поставки; ``terms_json``
хранит реквизиты покупателя по УНП (registry.lookup), чтобы не править shared-схему
Counterparty.

Revision ID: 0043
Revises: 0042
Create Date: 2026-06-24
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
        sa.Column("is_active", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("code", name="uq_contract_template_code"),
        schema="sales",
    )
    op.add_column("deal_document", sa.Column("template_id", sa.Integer(), nullable=True), schema="sales")
    op.add_column("deal_document", sa.Column("payment_terms", sa.String(length=255), nullable=True), schema="sales")
    op.add_column("deal_document", sa.Column("delivery_terms", sa.String(length=255), nullable=True), schema="sales")
    op.add_column("deal_document", sa.Column("terms_json", sa.JSON(), nullable=True), schema="sales")


def downgrade() -> None:
    for col in ("terms_json", "delivery_terms", "payment_terms", "template_id"):
        op.drop_column("deal_document", col, schema="sales")
    op.drop_table("contract_template", schema="sales")
