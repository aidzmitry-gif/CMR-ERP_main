"""refs: мастер-поля SKU под landed cost/таможню — volume_m3, vat_code (+ ref_sku_version)

Добавляет «горячие» типизированные поля номенклатуры:
- ``volume_m3`` — объём (м³) для разнесения фрахта по объёму (вес уже был);
- ``vat_code`` — свой код НДС (мягкая ссылка на ``ref_vat_rate``); None → наследуется от группы.

Те же поля — в ``ref_sku_version`` (SCD2-снимок мастер-полей; см. core/services/sku_history).
Поля nullable: старые строки не ломаются. Габариты Д×Ш×В остаются в ``attributes`` (свободные).

Revision ID: 0070
Revises: 0069
Create Date: 2026-06-28

Примечание: номер взят атомарно scripts/next_migration.py (refs); down_revision — реальный head.
"""
import sqlalchemy as sa
from alembic import op

revision = "0070"
down_revision = "0069"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("sku", "ref_sku_version"):
        op.add_column(table, sa.Column("volume_m3", sa.Float(), nullable=True))
        op.add_column(table, sa.Column("vat_code", sa.String(16), nullable=True))


def downgrade() -> None:
    for table in ("sku", "ref_sku_version"):
        op.drop_column(table, "vat_code")
        op.drop_column(table, "volume_m3")
