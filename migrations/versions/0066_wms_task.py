"""wms: складские задачи (put-away / pick)

``wms.task`` — задача кладовщику: размещение (put-away, авто после accept приёмки) или
подбор (pick, по резерву). Завершение пишет движение: put-away → transfer приёмная→
постоянная ячейка, pick → расход reason=pick. Операционные данные WMS; 1С не трогаем.

Revision ID: 0066
Revises: 0065
Create Date: 2026-06-28

Примечание: номер взят атомарно через scripts/next_migration.py (полоса «Склад/WMS»).
"""
import sqlalchemy as sa
from alembic import op

revision = "0066"
down_revision = "0065"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "task",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), server_default="open", nullable=False),
        sa.Column("sku_code", sa.String(64), nullable=False),
        sa.Column("qty", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.Column("warehouse", sa.String(128), server_default="Главный", nullable=False),
        sa.Column("from_location_id", sa.Integer(), nullable=True),
        sa.Column("to_location_id", sa.Integer(), nullable=True),
        sa.Column("doc_ref", sa.String(64), server_default="", nullable=False),
        sa.Column("assignee", sa.String(128), server_default="", nullable=False),
        sa.Column("priority", sa.String(16), server_default="normal", nullable=False),
        sa.Column("note", sa.String(255), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("done_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["from_location_id"], ["wms.location.id"],
            name=op.f("fk_task_from_location_id_location"),
        ),
        sa.ForeignKeyConstraint(
            ["to_location_id"], ["wms.location.id"],
            name=op.f("fk_task_to_location_id_location"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_task")),
        schema="wms",
    )
    op.create_index(op.f("ix_wms_task_kind"), "task", ["kind"], schema="wms")
    op.create_index(op.f("ix_wms_task_status"), "task", ["status"], schema="wms")


def downgrade() -> None:
    op.drop_index(op.f("ix_wms_task_status"), "task", schema="wms")
    op.drop_index(op.f("ix_wms_task_kind"), "task", schema="wms")
    op.drop_table("task", schema="wms")
