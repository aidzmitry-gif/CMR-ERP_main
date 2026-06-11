"""sales: Сделки 2.0 — отказ+причины (SALES-40), история стадий+поля (SALES-43),
прогноз (SALES-44), прочтение сообщений (SALES-49)

Revision ID: 0031
Revises: 0030
Create Date: 2026-06-11
"""
import sqlalchemy as sa
from alembic import op

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SALES-44 / SALES-43 / SALES-40: новые поля сделки
    op.add_column("deal", sa.Column("probability", sa.Integer(), nullable=True), schema="sales")
    op.add_column("deal", sa.Column("expected_close_date", sa.String(length=32), nullable=True), schema="sales")
    op.add_column("deal", sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False), schema="sales")
    op.add_column("deal", sa.Column("stage_changed_at", sa.DateTime(), server_default=sa.func.now(), nullable=False), schema="sales")
    op.add_column("deal", sa.Column("lost_reason_code", sa.String(length=32), nullable=True), schema="sales")
    op.add_column("deal", sa.Column("lost_comment", sa.String(length=255), nullable=True), schema="sales")

    # SALES-49: признак прочтения входящего сообщения
    op.add_column("message", sa.Column("read_at", sa.DateTime(), nullable=True), schema="sales")

    # SALES-40: справочник причин отказа
    op.create_table(
        "loss_reason",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=128), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.UniqueConstraint("code", name="uq_loss_reason_code"),
        schema="sales",
    )

    # SALES-43: история смены стадий сделки
    op.create_table(
        "deal_stage_event",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("deal_id", sa.Integer(), sa.ForeignKey("sales.deal.id"), nullable=False),
        sa.Column("from_stage", sa.String(length=32), nullable=True),
        sa.Column("to_stage", sa.String(length=32), nullable=False),
        sa.Column("changed_by", sa.String(length=128), server_default="", nullable=False),
        sa.Column("changed_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        schema="sales",
    )

    # дефолтные причины отказа (есть «из коробки»)
    loss_reason = sa.table(
        "loss_reason",
        sa.column("code", sa.String),
        sa.column("title", sa.String),
        sa.column("sort_order", sa.Integer),
        sa.column("active", sa.Boolean),
        schema="sales",
    )
    op.bulk_insert(
        loss_reason,
        [
            {"code": "price", "title": "Дорого / не прошли по цене", "sort_order": 1, "active": True},
            {"code": "competitor", "title": "Ушёл к конкуренту", "sort_order": 2, "active": True},
            {"code": "no_need", "title": "Нет потребности", "sort_order": 3, "active": True},
            {"code": "no_answer", "title": "Не дозвонились / нет ответа", "sort_order": 4, "active": True},
            {"code": "timing", "title": "Не тот срок поставки", "sort_order": 5, "active": True},
            {"code": "no_stock", "title": "Нет товара на складе", "sort_order": 6, "active": True},
            {"code": "other", "title": "Другое", "sort_order": 7, "active": True},
        ],
    )


def downgrade() -> None:
    op.drop_table("deal_stage_event", schema="sales")
    op.drop_table("loss_reason", schema="sales")
    op.drop_column("message", "read_at", schema="sales")
    for col in (
        "lost_comment", "lost_reason_code", "stage_changed_at",
        "created_at", "expected_close_date", "probability",
    ):
        op.drop_column("deal", col, schema="sales")
