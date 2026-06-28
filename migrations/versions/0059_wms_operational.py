"""wms: операционное ядро — топология (location) + измерения движений

``wms.location`` — зоны/ячейки адресного хранения. В ``wms.stock_movement`` добавлены
измерения операционного журнала: ``reason`` (receipt|shipment|reserve|release|transfer|
adjustment), ``location_id`` (FK → wms.location), ``batch_ref`` (партия), ``doc_ref``
(документ-источник / связка пары перемещения), ``note``.

WMS НЕ источник истины остатка (1С — истина, фаза 1): журнал ДУБЛИРУЕТ движения,
оперативный остаток = знаковая сумма (in − out), его сверяют с 1С.

Revision ID: 0059
Revises: 0058
Create Date: 2026-06-27

Примечание: номер взят атомарно через scripts/next_migration.py (полоса «Склад/WMS»).
Чейн: …→ 0058 (wms inventory) → 0059 (этот).
"""
import sqlalchemy as sa
from alembic import op

revision = "0059"
down_revision = "0058"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "location",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("warehouse", sa.String(128), server_default="Главный", nullable=False),
        sa.Column("zone", sa.String(64), server_default="", nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("title", sa.String(255), server_default="", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_location")),
        schema="wms",
    )
    op.add_column(
        "stock_movement",
        sa.Column("reason", sa.String(32), server_default="", nullable=False),
        schema="wms",
    )
    op.add_column(
        "stock_movement", sa.Column("location_id", sa.Integer(), nullable=True), schema="wms"
    )
    op.add_column(
        "stock_movement",
        sa.Column("batch_ref", sa.String(64), server_default="", nullable=False),
        schema="wms",
    )
    op.add_column(
        "stock_movement",
        sa.Column("doc_ref", sa.String(64), server_default="", nullable=False),
        schema="wms",
    )
    op.add_column(
        "stock_movement",
        sa.Column("note", sa.String(255), server_default="", nullable=False),
        schema="wms",
    )
    op.create_foreign_key(
        op.f("fk_stock_movement_location_id_location"),
        "stock_movement",
        "location",
        ["location_id"],
        ["id"],
        source_schema="wms",
        referent_schema="wms",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_stock_movement_location_id_location"),
        "stock_movement",
        schema="wms",
        type_="foreignkey",
    )
    op.drop_column("stock_movement", "note", schema="wms")
    op.drop_column("stock_movement", "doc_ref", schema="wms")
    op.drop_column("stock_movement", "batch_ref", schema="wms")
    op.drop_column("stock_movement", "location_id", schema="wms")
    op.drop_column("stock_movement", "reason", schema="wms")
    op.drop_table("location", schema="wms")
