"""core: shared-kernel reference data (units, currency(+rate), country, bank, vat(+history)) + sku.attributes

Системные справочники ядра в схеме ``public``:
- ``ref_unit``, ``ref_currency``, ``ref_country``, ``ref_bank`` — простые (архив, без истории);
- ``ref_currency_rate``, ``ref_vat_rate`` — историчные (SCD Type 2, полуоткрытый интервал
  ``[start_date, end_date)``; текущая версия — ``end_date IS NULL``);
- ``sku.attributes`` — JSONB переменных характеристик + GIN-индекс для поиска по атрибутам.

Revision ID: 0037
Revises: 0036
Create Date: 2026-06-14

Примечание: чейн линейный 0036 → 0037. Если параллельная сессия уже заняла 0037 —
перенумеровать (как было с 0034/0036).
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ref_unit",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=64), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.UniqueConstraint("code", name="uq_ref_unit_code"),
    )
    op.create_table(
        "ref_currency",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(length=8), nullable=False),
        sa.Column("title", sa.String(length=64), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.UniqueConstraint("code", name="uq_ref_currency_code"),
    )
    op.create_table(
        "ref_country",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(length=8), nullable=False),
        sa.Column("title", sa.String(length=128), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.UniqueConstraint("code", name="uq_ref_country_code"),
    )
    op.create_table(
        "ref_bank",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("swift", sa.String(length=16), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.UniqueConstraint("code", name="uq_ref_bank_code"),
    )
    op.create_table(
        "ref_currency_rate",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("currency_code", sa.String(length=8), nullable=False),
        sa.Column("rate", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
    )
    op.create_index(
        "ix_ref_currency_rate_lookup", "ref_currency_rate", ["currency_code", "start_date"]
    )
    op.create_table(
        "ref_vat_rate",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=64), nullable=False),
        sa.Column("rate", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
    )
    op.create_index("ix_ref_vat_rate_lookup", "ref_vat_rate", ["code", "start_date"])

    # переменные характеристики номенклатуры — JSONB + GIN (фасетный поиск по атрибутам)
    op.add_column(
        "sku",
        sa.Column(
            "attributes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.create_index("ix_sku_attributes", "sku", ["attributes"], postgresql_using="gin")


def downgrade() -> None:
    op.drop_index("ix_sku_attributes", table_name="sku")
    op.drop_column("sku", "attributes")
    op.drop_index("ix_ref_vat_rate_lookup", table_name="ref_vat_rate")
    op.drop_table("ref_vat_rate")
    op.drop_index("ix_ref_currency_rate_lookup", table_name="ref_currency_rate")
    op.drop_table("ref_currency_rate")
    op.drop_table("ref_bank")
    op.drop_table("ref_country")
    op.drop_table("ref_currency")
    op.drop_table("ref_unit")
