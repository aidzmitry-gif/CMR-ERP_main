"""core: горячие поля номенклатуры — вес, ТН ВЭД, срок годности, архив, provenance (M4)

Sku обогащается мастер-полями, нужными продавцу/расчёту в момент сделки:
- weight_kg — для распределения фрахта в landed cost;
- tnved_code — ТН ВЭД (пошлина из справочника → landed cost);
- shelf_life_days — срок годности (FEFO-алерт <1 года);
- is_active — архив вместо удаления (как у контрагента);
- provenance (JSON) — field-level происхождение (единый слой с Counterparty, M2).

Revision ID: 0047
Revises: 0046
Create Date: 2026-06-25
"""
import sqlalchemy as sa
from alembic import op

revision = "0047"
down_revision = "0046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sku", sa.Column("weight_kg", sa.Float(), nullable=True))
    op.add_column("sku", sa.Column("tnved_code", sa.String(length=16), nullable=True))
    op.add_column("sku", sa.Column("shelf_life_days", sa.Integer(), nullable=True))
    op.add_column(
        "sku",
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )
    op.add_column(
        "sku",
        sa.Column("provenance", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("sku", "provenance")
    op.drop_column("sku", "is_active")
    op.drop_column("sku", "shelf_life_days")
    op.drop_column("sku", "tnved_code")
    op.drop_column("sku", "weight_kg")
