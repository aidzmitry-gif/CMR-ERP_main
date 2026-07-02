"""core: код ТН ВЭД по умолчанию на группе номенклатуры (наследование товаром)

``ref_nomenclature_category.tnved_code`` — код ТН ВЭД группы (мягкая ссылка на ref_tnved,
не FK). Товар без собственного ``Sku.tnved_code`` наследует его вверх по дереву групп
(parent_id) — резолв в ``core.services.tnved.effective_code_for_sku``. Закрывает ручное
проставление ТН ВЭД на каждый товар: задал на группе → подтянулось ко всем внутри.

Revision ID: 0050
Revises: 0049
Create Date: 2026-06-26

Примечание: чейн линейный 0049 → 0050. Если параллельная сессия уже заняла 0050 —
перенумеровать (как было с 0034/0036).
"""
import sqlalchemy as sa
from alembic import op

revision = "0050"
down_revision = "0049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ref_nomenclature_category",
        sa.Column("tnved_code", sa.String(length=16), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ref_nomenclature_category", "tnved_code")
