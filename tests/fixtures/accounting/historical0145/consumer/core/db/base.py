"""Декларативная база SQLAlchemy 2 и единое соглашение об именах ограничений.

Все ORM-модели (shared kernel ядра и таблицы модулей) наследуются от `Base`,
поэтому `Base.metadata` содержит полную схему — её использует Alembic для миграций.
Модули объявляют свои таблицы в собственных схемах через ``__table_args__`` (§2.4).
"""
from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# единые имена индексов/ключей — стабильные имена в миграциях
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
