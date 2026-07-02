"""refs: partial-unique индекс SCD2 — ровно одна открытая версия на natural key

Единственность открытой (``end_date IS NULL``) версии для четырёх датированных
справочников (курс валюты, ставка НДС, ТН ВЭД, версия SKU) до сих пор держалась ТОЛЬКО
прикладной проверкой ``core.services.scd2.add_version`` (читает current_version перед
вставкой, не коммитит). Две ПАРАЛЛЕЛЬНЫЕ транзакции обе могли не увидеть открытую версию
друг друга и обе вставить новую → две открытые версии по одному ключу (гонка).

Закрываем гонку на уровне БД: partial-unique индекс ``UNIQUE (<natural_key>) WHERE
end_date IS NULL`` — вторую открытую версию по тому же ключу отклонит сама Postgres
(IntegrityError). Закрытые версии (``end_date`` задан) под предикат не попадают, поэтому
история версий по ключу не ограничивается — уникальна только текущая открытая.

Источник истины ТОЛЬКО для Postgres: SQLite-dev поднимает схему через ORM ``create_all``
(минуя Alembic), декларативные ORM-модели не трогаем (``core/domain/reference.py``).

Revision ID: 0084
Revises: 0083
Create Date: 2026-07-02

Примечание: номер 0084 выделен координатором (не через scripts/next_migration.py);
down_revision — реальный head 0083. Цепочка линейна. Имена индексов заданы явно (не
NAMING_CONVENTION auto-name), по образцу ix_ref_*_lookup.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0084"
down_revision = "0083"
branch_labels = None
depends_on = None

# (имя индекса, таблица, natural-key колонка)
_INDEXES = (
    ("uq_ref_currency_rate_open", "ref_currency_rate", "currency_code"),
    ("uq_ref_vat_rate_open", "ref_vat_rate", "code"),
    ("uq_ref_tnved_open", "ref_tnved", "code"),
    ("uq_ref_sku_version_open", "ref_sku_version", "sku_code"),
)


def upgrade() -> None:
    for name, table, column in _INDEXES:
        op.create_index(
            name, table, [column],
            unique=True, postgresql_where=sa.text("end_date IS NULL"),
        )


def downgrade() -> None:
    for name, table, _column in reversed(_INDEXES):
        op.drop_index(name, table_name=table)
