"""Окружение Alembic.

Собирает целевую метадату из `Base` + ORM-моделей всех включённых модулей
(shared kernel ядра и таблицы модулей), берёт URL БД из настроек приложения,
поддерживает offline (`--sql`) и online режимы. ``include_schemas=True`` —
чтобы Alembic видел таблицы в схемах модулей (например, ``sales``).
"""
from __future__ import annotations

import importlib
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Регистрируем модели на Base.metadata: сначала shared kernel ядра,
# затем модели каждого включённого модуля (если у модуля они есть).
import core.domain.models  # noqa: F401,E402
from config.modules import ENABLED_MODULES
from config.settings import get_settings
from core.db.base import Base

for _mod in ENABLED_MODULES:
    try:
        importlib.import_module(f"modules.{_mod}.models")
    except ModuleNotFoundError:
        pass

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url() -> str:
    return get_settings().database_url


def run_migrations_offline() -> None:
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
        version_table_schema=None,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = get_url()
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
