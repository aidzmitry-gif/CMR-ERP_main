"""core: общие данные группы по умолчанию (НДС/ед.изм/страна) — наследование товаром

``ref_nomenclature_category.{vat_code, unit, country}`` — значения по умолчанию группы
(мягкие ссылки на ref_vat_rate / ref_unit / ref_country, не FK). Товар без собственного
значения наследует их вверх по дереву групп (parent_id) — резолв в
``core.services.tnved.effective_group_field``. Расширяет уже существующий ``tnved_code``
(0050): «общие данные группы для товаров в ней».

Revision ID: 0054
Revises: 0053
Create Date: 2026-06-26

Примечание: чейн линейный 0053 → 0054. Если параллельная сессия уже заняла 0054 —
перенумеровать (как было с 0034/0036).
"""
import sqlalchemy as sa
from alembic import op

revision = "0054"
down_revision = "0053"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ref_nomenclature_category",
        sa.Column("vat_code", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "ref_nomenclature_category",
        sa.Column("unit", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "ref_nomenclature_category",
        sa.Column("country", sa.String(length=8), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ref_nomenclature_category", "country")
    op.drop_column("ref_nomenclature_category", "unit")
    op.drop_column("ref_nomenclature_category", "vat_code")
