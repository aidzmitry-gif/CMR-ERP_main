"""production: plan deal_id + source_event (событийная шина)

Добавляет в ``production.production_plan``:
- ``deal_id`` (INTEGER, nullable, indexed) — связь с продажной сделкой;
  используется для идемпотентности при повторном emit ``sales.deal.handoff``.
- ``source_event`` (VARCHAR(128), nullable) — имя события-источника («sales.deal.handoff»).

Revision ID: 0041
Revises: 0040
Create Date: 2026-06-29
"""
import sqlalchemy as sa
from alembic import op

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "production_plan",
        sa.Column("deal_id", sa.Integer(), nullable=True),
        schema="production",
    )
    op.create_index(
        "ix_production_plan_deal_id",
        "production_plan",
        ["deal_id"],
        schema="production",
    )
    op.add_column(
        "production_plan",
        sa.Column("source_event", sa.String(length=128), nullable=True),
        schema="production",
    )


def downgrade() -> None:
    op.drop_index("ix_production_plan_deal_id", table_name="production_plan", schema="production")
    op.drop_column("production_plan", "deal_id", schema="production")
    op.drop_column("production_plan", "source_event", schema="production")
