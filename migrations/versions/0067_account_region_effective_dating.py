"""refs: датированный ввод/вывод из оборота для Account и Region (effective_from/to)

Мягкий вывод справочника по дате (дополняет is_active): счёт/регион действует в периоде
``[effective_from, effective_to)``; ``effective_to IS NULL`` = в силе. Не полноценный SCD2
(значения не датируются по версиям) — только период действия записи. Поля nullable: старые
строки = бессрочно действующие (оба NULL).

Revision ID: 0067
Revises: 0066
Create Date: 2026-06-28

Примечание: номер взят атомарно через scripts/next_migration.py (refs); down_revision —
реальный head на момент резерва. Цепочка линейна.
"""
import sqlalchemy as sa
from alembic import op

revision = "0067"
down_revision = "0066"
branch_labels = None
depends_on = None

_TABLES = ("ref_account", "ref_region")


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(table, sa.Column("effective_from", sa.Date(), nullable=True))
        op.add_column(table, sa.Column("effective_to", sa.Date(), nullable=True))


def downgrade() -> None:
    for table in _TABLES:
        op.drop_column(table, "effective_to")
        op.drop_column(table, "effective_from")
