"""leads: lead_attachment — метаданные вложений лида (скан заявки/письмо/ручная загрузка).

Байты файла — на диске (``modules/leads/storage.py``), НЕ в этой таблице: в отличие
от sales.company_branding (0090, логотип — маленький, живёт как data-URI в колонке),
вложения лида (сканы/xlsx) могут весить несколько МБ — раздувать Postgres-строки
не нужно. FK на ``leads.lead`` — обе таблицы в одной схеме, полноценный (не soft-link,
как ``lead.deal_id`` на cross-schema sales.deal).

Revision ID: 0091
Revises: 0090
Create Date: 2026-07-04
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0091"
down_revision = "0090"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lead_attachment",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "lead_id",
            sa.Integer(),
            sa.ForeignKey("leads.lead.id"),
            nullable=False,
        ),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=16), server_default="manual", nullable=False),
        sa.Column("storage_path", sa.String(length=512), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        schema="leads",
    )
    op.create_index(
        "ix_lead_attachment_lead_id", "lead_attachment", ["lead_id"], schema="leads"
    )


def downgrade() -> None:
    op.drop_index("ix_lead_attachment_lead_id", table_name="lead_attachment", schema="leads")
    op.drop_table("lead_attachment", schema="leads")
