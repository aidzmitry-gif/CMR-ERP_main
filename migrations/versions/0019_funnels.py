"""funnels: модули-воронки (закупки/производство/склад/HR/офис/юр/база знаний)

Расширяет procurement и production до воронок (status → stage + поля карточки),
добавляет складские операции (wms.warehouse_op) и кандидатов (hr.candidate),
создаёт новые модули office/legal/knowledge.

Revision ID: 0019
Revises: 0018
Create Date: 2026-06-05
"""
import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- procurement: status → stage (воронка sourcing-цикла) + поля карточки ---
    op.add_column("purchase_request", sa.Column("number", sa.String(length=64), server_default="", nullable=False), schema="procurement")
    op.add_column("purchase_request", sa.Column("amount", sa.Numeric(precision=14, scale=2), server_default="0", nullable=False), schema="procurement")
    op.add_column("purchase_request", sa.Column("priority", sa.String(length=32), server_default="Средний", nullable=False), schema="procurement")
    op.add_column("purchase_request", sa.Column("owner", sa.String(length=128), server_default="", nullable=False), schema="procurement")
    op.add_column("purchase_request", sa.Column("stage", sa.String(length=32), server_default="need", nullable=False), schema="procurement")
    op.add_column("purchase_request", sa.Column("due_date", sa.String(length=32), nullable=True), schema="procurement")
    op.drop_column("purchase_request", "status", schema="procurement")

    # --- production: status → stage (этапы цеха) + поля наряда ---
    op.add_column("production_order", sa.Column("number", sa.String(length=64), server_default="", nullable=False), schema="production")
    op.add_column("production_order", sa.Column("progress", sa.Integer(), server_default="0", nullable=False), schema="production")
    op.add_column("production_order", sa.Column("priority", sa.String(length=32), server_default="Средний", nullable=False), schema="production")
    op.add_column("production_order", sa.Column("owner", sa.String(length=128), server_default="", nullable=False), schema="production")
    op.add_column("production_order", sa.Column("stage", sa.String(length=32), server_default="queue", nullable=False), schema="production")
    op.add_column("production_order", sa.Column("due_date", sa.String(length=32), nullable=True), schema="production")
    op.drop_column("production_order", "status", schema="production")

    # --- wms: складские операции (воронка поступление → отгрузка) ---
    op.create_table(
        "warehouse_op",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("number", sa.String(length=64), server_default="", nullable=False),
        sa.Column("counterparty", sa.String(length=255), server_default="", nullable=False),
        sa.Column("title", sa.String(length=255), server_default="", nullable=False),
        sa.Column("items_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), server_default="0", nullable=False),
        sa.Column("zone", sa.String(length=64), server_default="", nullable=False),
        sa.Column("priority", sa.String(length=32), server_default="Средний", nullable=False),
        sa.Column("owner", sa.String(length=128), server_default="", nullable=False),
        sa.Column("stage", sa.String(length=32), server_default="inbound", nullable=False),
        sa.Column("op_date", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        schema="wms",
    )

    # --- hr: кандидаты (воронка подбора) ---
    op.create_table(
        "candidate",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("number", sa.String(length=64), server_default="", nullable=False),
        sa.Column("name", sa.String(length=255), server_default="", nullable=False),
        sa.Column("position", sa.String(length=128), server_default="", nullable=False),
        sa.Column("salary", sa.Numeric(precision=14, scale=2), server_default="0", nullable=False),
        sa.Column("recruiter", sa.String(length=128), server_default="", nullable=False),
        sa.Column("priority", sa.String(length=32), server_default="Средний", nullable=False),
        sa.Column("stage", sa.String(length=32), server_default="new", nullable=False),
        sa.Column("next_step", sa.String(length=255), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        schema="hr",
    )

    # --- office: документы по сделкам (новый модуль) ---
    op.execute("CREATE SCHEMA IF NOT EXISTS office")
    op.create_table(
        "office_doc",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("number", sa.String(length=64), server_default="", nullable=False),
        sa.Column("company", sa.String(length=255), server_default="", nullable=False),
        sa.Column("title", sa.String(length=255), server_default="", nullable=False),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), server_default="0", nullable=False),
        sa.Column("delivery", sa.String(length=64), server_default="", nullable=False),
        sa.Column("docs_status", sa.String(length=64), server_default="", nullable=False),
        sa.Column("priority", sa.String(length=32), server_default="Средний", nullable=False),
        sa.Column("owner", sa.String(length=128), server_default="", nullable=False),
        sa.Column("stage", sa.String(length=32), server_default="ready", nullable=False),
        sa.Column("next_step", sa.String(length=255), server_default="", nullable=False),
        sa.Column("op_date", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        schema="office",
    )

    # --- legal: юр-дела и документы (новый модуль) ---
    op.execute("CREATE SCHEMA IF NOT EXISTS legal")
    op.create_table(
        "legal_case",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("number", sa.String(length=64), server_default="", nullable=False),
        sa.Column("company", sa.String(length=255), server_default="", nullable=False),
        sa.Column("title", sa.String(length=255), server_default="", nullable=False),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), server_default="0", nullable=False),
        sa.Column("urgency", sa.String(length=32), server_default="Обычный", nullable=False),
        sa.Column("owner", sa.String(length=128), server_default="", nullable=False),
        sa.Column("stage", sa.String(length=32), server_default="inbox", nullable=False),
        sa.Column("next_step", sa.String(length=255), server_default="", nullable=False),
        sa.Column("due_date", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        schema="legal",
    )

    # --- knowledge: курсы программы обучения (новый модуль) ---
    op.execute("CREATE SCHEMA IF NOT EXISTS knowledge")
    op.create_table(
        "course",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("number", sa.String(length=64), server_default="", nullable=False),
        sa.Column("title", sa.String(length=255), server_default="", nullable=False),
        sa.Column("description", sa.String(length=255), server_default="", nullable=False),
        sa.Column("kind", sa.String(length=32), server_default="Документ", nullable=False),
        sa.Column("duration", sa.Integer(), server_default="0", nullable=False),
        sa.Column("progress", sa.Integer(), server_default="0", nullable=False),
        sa.Column("audience", sa.String(length=64), server_default="", nullable=False),
        sa.Column("stage", sa.String(length=32), server_default="trial", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        schema="knowledge",
    )


def downgrade() -> None:
    op.drop_table("course", schema="knowledge")
    op.execute("DROP SCHEMA IF EXISTS knowledge")
    op.drop_table("legal_case", schema="legal")
    op.execute("DROP SCHEMA IF EXISTS legal")
    op.drop_table("office_doc", schema="office")
    op.execute("DROP SCHEMA IF EXISTS office")
    op.drop_table("candidate", schema="hr")
    op.drop_table("warehouse_op", schema="wms")

    op.add_column("production_order", sa.Column("status", sa.String(length=32), server_default="planned", nullable=False), schema="production")
    op.drop_column("production_order", "due_date", schema="production")
    op.drop_column("production_order", "stage", schema="production")
    op.drop_column("production_order", "owner", schema="production")
    op.drop_column("production_order", "priority", schema="production")
    op.drop_column("production_order", "progress", schema="production")
    op.drop_column("production_order", "number", schema="production")

    op.add_column("purchase_request", sa.Column("status", sa.String(length=32), server_default="new", nullable=False), schema="procurement")
    op.drop_column("purchase_request", "due_date", schema="procurement")
    op.drop_column("purchase_request", "stage", schema="procurement")
    op.drop_column("purchase_request", "owner", schema="procurement")
    op.drop_column("purchase_request", "priority", schema="procurement")
    op.drop_column("purchase_request", "amount", schema="procurement")
    op.drop_column("purchase_request", "number", schema="procurement")
