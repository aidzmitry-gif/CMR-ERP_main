"""core: field-level provenance + survivorship-правила как данные (M2)

- ``counterparty.provenance`` (JSON) — источник КАЖДОГО поля: ``{field: {source, at}}``;
- ``survivorship_rule`` — правило слияния по полю (стратегия + приоритет источников),
  выносит хардкод ``_SURVIVORSHIP_FIELDS`` из ``core/services/mdm.py`` в данные.

Revision ID: 0044
Revises: 0043
Create Date: 2026-06-25
"""
import sqlalchemy as sa
from alembic import op

revision = "0044"
down_revision = "0043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "counterparty",
        sa.Column("provenance", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
    )
    op.create_table(
        "survivorship_rule",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("field", sa.String(length=64), nullable=False),
        sa.Column("strategy", sa.String(length=32), nullable=False),
        sa.Column("source_priority", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
    )
    op.create_index(
        "ix_survivorship_rule_entity_type", "survivorship_rule", ["entity_type"]
    )
    op.create_unique_constraint(
        "uq_survivorship_rule_entity_field", "survivorship_rule", ["entity_type", "field"]
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_survivorship_rule_entity_field", "survivorship_rule", type_="unique"
    )
    op.drop_index("ix_survivorship_rule_entity_type", table_name="survivorship_rule")
    op.drop_table("survivorship_rule")
    op.drop_column("counterparty", "provenance")
