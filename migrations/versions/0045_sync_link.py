"""core: sync_link — связь записи ERP с внешней системой + статус выгрузки (M3)

Одна таблица под любую сущность/систему: внешний id, происхождение, направление, состояние
очереди выгрузки (local/pending/synced/error). Поток ERP→1С: запись с origin="erp" → pending
→ relay подбирает → post_document → synced+external_ref. Конфликты правит survivorship (M2).

Revision ID: 0045
Revises: 0044
Create Date: 2026-06-25
"""
import sqlalchemy as sa
from alembic import op

revision = "0045"
down_revision = "0044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sync_link",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("system", sa.String(length=32), server_default="1c", nullable=False),
        sa.Column("external_ref", sa.String(length=128), nullable=True),
        sa.Column("origin", sa.String(length=16), nullable=False),
        sa.Column("direction", sa.String(length=8), server_default="out", nullable=False),
        sa.Column("state", sa.String(length=16), server_default="local", nullable=False),
        sa.Column("last_synced_at", sa.DateTime(), nullable=True),
        sa.Column("error_text", sa.String(length=255), nullable=True),
    )
    # один линк на (сущность, запись, система) — идемпотентность очереди
    op.create_unique_constraint(
        "uq_sync_link_entity_system", "sync_link", ["entity_type", "entity_id", "system"]
    )
    # выборка pending для relay
    op.create_index("ix_sync_link_state", "sync_link", ["state"])


def downgrade() -> None:
    op.drop_index("ix_sync_link_state", table_name="sync_link")
    op.drop_constraint("uq_sync_link_entity_system", "sync_link", type_="unique")
    op.drop_table("sync_link")
