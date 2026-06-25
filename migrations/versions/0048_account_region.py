"""core: план счетов (РБ) + регионы/города — иерархические справочники (parent_id)

Два классификатора-справочника ядра в схеме ``public`` (adjacency list, как группы
номенклатуры 0040):
- ``ref_account`` — план счетов бухучёта РБ (постановление Минфина №50): синтетические
  счета + субсчета через ``parent_id``, ``kind`` (актив/пассив/активно-пассивный);
- ``ref_region`` — гео-справочник (область→район→город) через ``parent_id``,
  ``kind`` (область/район/город). Адреса контрагентов + territory аналитики продаж.

Revision ID: 0048
Revises: 0047
Create Date: 2026-06-26

Примечание: чейн линейный 0047 → 0048. Если параллельная сессия уже заняла 0048 —
перенумеровать (как было с 0034/0036).
"""
import sqlalchemy as sa
from alembic import op

revision = "0048"
down_revision = "0047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ref_account",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=True),
        sa.Column("parent_id", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.UniqueConstraint("code", name="uq_ref_account_code"),
        sa.ForeignKeyConstraint(
            ["parent_id"], ["ref_account.id"], name="fk_ref_account_parent"
        ),
    )
    op.create_index("ix_ref_account_parent", "ref_account", ["parent_id"])

    op.create_table(
        "ref_region",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=True),
        sa.Column("parent_id", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.UniqueConstraint("code", name="uq_ref_region_code"),
        sa.ForeignKeyConstraint(
            ["parent_id"], ["ref_region.id"], name="fk_ref_region_parent"
        ),
    )
    op.create_index("ix_ref_region_parent", "ref_region", ["parent_id"])


def downgrade() -> None:
    op.drop_index("ix_ref_region_parent", table_name="ref_region")
    op.drop_table("ref_region")
    op.drop_index("ix_ref_account_parent", table_name="ref_account")
    op.drop_table("ref_account")
