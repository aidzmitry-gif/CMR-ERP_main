"""core: группы (категории) номенклатуры — иерархия (parent_id) + sku.category_id

Иерархический справочник-классификатор в схеме ``public``:
- ``ref_nomenclature_category`` — adjacency list (``parent_id`` self-FK = истина дерева),
  ``code`` уникален; дерево обходится рекурсивным CTE (производный ltree — отдельной
  Postgres-итерацией);
- ``sku.category_id`` — ссылка позиции номенклатуры на группу (nullable).

Revision ID: 0040
Revises: 0039
Create Date: 2026-06-15

Примечание: чейн линейный 0039 → 0040. Если параллельная сессия уже заняла 0040 —
перенумеровать (как было с 0034/0036).
"""
import sqlalchemy as sa
from alembic import op

revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ref_nomenclature_category",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("parent_id", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.UniqueConstraint("code", name="uq_ref_nomenclature_category_code"),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["ref_nomenclature_category.id"],
            name="fk_ref_nom_category_parent",  # короткое имя: PG лимит идентификатора 63 символа
        ),
    )
    op.create_index(
        "ix_ref_nom_category_parent", "ref_nomenclature_category", ["parent_id"]
    )

    op.add_column("sku", sa.Column("category_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_sku_category_id_ref_nomenclature_category",
        "sku",
        "ref_nomenclature_category",
        ["category_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_sku_category_id_ref_nomenclature_category", "sku", type_="foreignkey"
    )
    op.drop_column("sku", "category_id")
    op.drop_index("ix_ref_nom_category_parent", table_name="ref_nomenclature_category")
    op.drop_table("ref_nomenclature_category")
