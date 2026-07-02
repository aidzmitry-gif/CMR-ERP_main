"""core: расширение pg_trgm для fuzzy-дедупа контрагентов по имени (M1)

``mdm.fuzzy_candidates`` на Postgres использует ``similarity(...)`` (триграммы) — функция
живёт в расширении pg_trgm. Без него запрос падает «function similarity does not exist».
Только Postgres; на SQLite миграции не применяются (create_all), fuzzy там — Python-фолбэк.

Revision ID: 0046
Revises: 0045
Create Date: 2026-06-25
"""
from alembic import op

revision = "0046"
down_revision = "0045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")


def downgrade() -> None:
    # расширение не удаляем: им могут пользоваться другие объекты/индексы (безопасный no-op)
    pass
