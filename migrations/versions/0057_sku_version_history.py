"""core: история мастер-характеристик SKU (SCD2) — ref_sku_version

``ref_sku_version`` — датированные СНИМКИ мастер-полей ``Sku`` (наименование, ед., группа,
вес, ТН ВЭД, срок годности, свободные характеристики) с полуоткрытым интервалом
``[start_date, end_date)``; текущая версия — ``end_date IS NULL``. Документ «на дату» видит
характеристики, действовавшие тогда (как курс валюты/НДС). Натуральный ключ — мягкий
``sku_code`` (без FK к ``sku.id``, как ``vat_code``/``tnved_code``) — не трогает схему ``Sku``.
Запись версий — ``core.services.sku_history.record_sku_version``; чтение — ``/system/refs/
sku-history`` + ``reference_query`` (as-of). Операционные данные (цена/остаток) сюда не кладём.

На Postgres ``attributes`` — JSONB (тип ``JSON`` SQLAlchemy маппится в ``jsonb`` диалектом),
server_default ``'{}'`` как у ``Sku.attributes``.

Revision ID: 0057
Revises: 0056
Create Date: 2026-06-27

Примечание: чейн линейный 0055 → 0056 (procurement landed_cost) → 0057 (этот). Номер выдан
координатором атомарно; down_revision = реальная голова 0056, НЕ 0055 (иначе форк-хед).
"""
import sqlalchemy as sa
from alembic import op

revision = "0057"
down_revision = "0056"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ref_sku_version",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("sku_code", sa.String(64), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("unit", sa.String(16), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=True),  # мягкая ссылка (снимок, не FK)
        sa.Column("weight_kg", sa.Float(), nullable=True),
        sa.Column("tnved_code", sa.String(16), nullable=True),
        sa.Column("shelf_life_days", sa.Integer(), nullable=True),
        sa.Column("attributes", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("start_date", sa.Date(), nullable=False),  # действует с (вкл.)
        sa.Column("end_date", sa.Date(), nullable=True),  # по (искл.); NULL = текущая
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ref_sku_version")),
    )
    op.create_index(
        "ix_ref_sku_version_lookup", "ref_sku_version", ["sku_code", "start_date"]
    )


def downgrade() -> None:
    op.drop_index("ix_ref_sku_version_lookup", "ref_sku_version")
    op.drop_table("ref_sku_version")
