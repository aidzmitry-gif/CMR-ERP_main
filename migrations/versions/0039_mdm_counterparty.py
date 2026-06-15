"""core: MDM контрагентов — golden record (is_active/merged_into_id) + counterparty_alias

- ``counterparty.is_active`` — архив дубля при слиянии (мягкое удаление);
- ``counterparty.merged_into_id`` — ссылка дубля на эталон (self-FK), NULL = самостоятельная;
- ``counterparty_alias`` — алиасы/источники эталона (1С, Bitrix, merge) для резолва и unmerge.

Revision ID: 0039
Revises: 0038
Create Date: 2026-06-15
"""
import sqlalchemy as sa
from alembic import op

revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "counterparty",
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )
    op.add_column("counterparty", sa.Column("merged_into_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_counterparty_merged_into_id_counterparty",
        "counterparty",
        "counterparty",
        ["merged_into_id"],
        ["id"],
    )
    op.create_table(
        "counterparty_alias",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("counterparty_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("external_ref", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["counterparty_id"],
            ["counterparty.id"],
            name="fk_counterparty_alias_counterparty_id_counterparty",
        ),
    )
    op.create_index(
        "ix_counterparty_alias_counterparty_id", "counterparty_alias", ["counterparty_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_counterparty_alias_counterparty_id", table_name="counterparty_alias")
    op.drop_table("counterparty_alias")
    op.drop_constraint(
        "fk_counterparty_merged_into_id_counterparty", "counterparty", type_="foreignkey"
    )
    op.drop_column("counterparty", "merged_into_id")
    op.drop_column("counterparty", "is_active")
