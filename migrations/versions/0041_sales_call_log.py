"""sales: журнал звонков (SALES-50) — таблица call_log

Окно входящего звонка: события облачной АТС (через коннектор integrations) склеиваются
по ``call_id`` в одну запись. Мягкие ссылки на shared kernel / hr / контакт — без
cross-schema FK; ``deal_id`` — FK на свою схему ``sales.deal``.

Revision ID: 0041
Revises: 0040
Create Date: 2026-06-23

Примечание: чейн линейный 0040 → 0041. Если параллельная сессия уже заняла 0041 —
перенумеровать (как было с 0034/0036).
"""
import sqlalchemy as sa
from alembic import op

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "call_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("call_id", sa.String(length=64), nullable=False),  # uniqueid провайдера
        sa.Column("direction", sa.String(length=8), server_default="in", nullable=False),  # in|out
        sa.Column("phone_e164", sa.String(length=32), nullable=True),  # клиент (нормализованный)
        sa.Column("did", sa.String(length=32), nullable=True),  # внешняя линия
        sa.Column("agent_ext", sa.String(length=8), nullable=True),  # внутренний номер сотрудника
        sa.Column("owner", sa.String(length=128), server_default="", nullable=False),  # продавец
        sa.Column("owner_id", sa.Integer(), nullable=True),  # мягкая ссылка hr.employee
        sa.Column("counterparty_id", sa.Integer(), nullable=True),  # мягкая ссылка shared kernel
        sa.Column("contact_id", sa.Integer(), nullable=True),  # мягкая ссылка shared kernel
        sa.Column("deal_id", sa.Integer(), nullable=True),
        # ringing → answered → ended | missed | busy | failed
        sa.Column("status", sa.String(length=16), server_default="ringing", nullable=False),
        sa.Column("result", sa.String(length=255), nullable=True),
        sa.Column("comment", sa.String(length=1000), nullable=True),
        sa.Column("recording_url", sa.String(length=255), nullable=True),
        sa.Column("started_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("answered_at", sa.DateTime(), nullable=True),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("duration_sec", sa.Integer(), nullable=True),  # разговор, сек
        sa.Column("hold_sec", sa.Integer(), nullable=True),  # общее время вызова, сек
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("call_id", name="uq_call_log_call_id"),
        sa.ForeignKeyConstraint(["deal_id"], ["sales.deal.id"], name="fk_call_log_deal"),
        schema="sales",
    )
    # журнал часто фильтруется по продавцу (поток/история) и статусу
    op.create_index("ix_call_log_owner", "call_log", ["owner"], schema="sales")
    op.create_index("ix_call_log_status", "call_log", ["status"], schema="sales")


def downgrade() -> None:
    op.drop_index("ix_call_log_status", table_name="call_log", schema="sales")
    op.drop_index("ix_call_log_owner", table_name="call_log", schema="sales")
    op.drop_table("call_log", schema="sales")
