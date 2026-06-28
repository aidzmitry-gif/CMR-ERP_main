"""wms: документ приёмки + QC-гейт (receipt / receipt_line)

``wms.receipt`` — документ приёмки (закупка/производство/вручную) со статусом QC;
``wms.receipt_line`` — строки (ожидаемое/принято/брак, целевая ячейка/партия).
Приходное движение пишется ТОЛЬКО после accept по фактически принятому кол-ву —
событие прихода рождает документ в ``pending_qc``, движений по нему нет. 1С не трогаем.

Revision ID: 0064
Revises: 0063
Create Date: 2026-06-28

Примечание: номер взят атомарно через scripts/next_migration.py (полоса «Склад/WMS»).
"""
import sqlalchemy as sa
from alembic import op

revision = "0064"
down_revision = "0063"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "receipt",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("number", sa.String(64), server_default="", nullable=False),
        sa.Column("source", sa.String(16), server_default="manual", nullable=False),
        sa.Column("entity_ref", sa.String(128), server_default="", nullable=False),
        sa.Column("warehouse", sa.String(128), server_default="Главный", nullable=False),
        sa.Column("status", sa.String(16), server_default="pending_qc", nullable=False),
        sa.Column("counterparty", sa.String(255), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("decided_by", sa.String(128), server_default="", nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_receipt")),
        schema="wms",
    )
    op.create_table(
        "receipt_line",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("receipt_id", sa.Integer(), nullable=False),
        sa.Column("sku_code", sa.String(64), nullable=False),
        sa.Column("sku_title", sa.String(255), server_default="", nullable=False),
        sa.Column("expected_qty", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.Column("accepted_qty", sa.Numeric(14, 2), nullable=True),
        sa.Column("rejected_qty", sa.Numeric(14, 2), nullable=True),
        sa.Column("reject_reason", sa.String(255), server_default="", nullable=False),
        sa.Column("location_id", sa.Integer(), nullable=True),
        sa.Column("batch_ref", sa.String(64), server_default="", nullable=False),
        sa.ForeignKeyConstraint(
            ["receipt_id"], ["wms.receipt.id"], name=op.f("fk_receipt_line_receipt_id_receipt")
        ),
        sa.ForeignKeyConstraint(
            ["location_id"], ["wms.location.id"],
            name=op.f("fk_receipt_line_location_id_location"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_receipt_line")),
        schema="wms",
    )
    op.create_index(
        op.f("ix_wms_receipt_line_receipt_id"), "receipt_line", ["receipt_id"], schema="wms"
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_wms_receipt_line_receipt_id"), "receipt_line", schema="wms")
    op.drop_table("receipt_line", schema="wms")
    op.drop_table("receipt", schema="wms")
