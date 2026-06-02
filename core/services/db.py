"""Доступ к БД: async SQLAlchemy 2 поверх psycopg3 (PostgreSQL 16 + pgvector).

Движок создаётся лениво (`init_engine`) и проверяется при старте приложения
(`connect`). Для удобства разработки без Docker поддержан SQLite-режим: схема
модулей (`sales`) отображается в основную через ``schema_translate_map``, а
таблицы создаются напрямую (минуя Alembic — в SQLite нет схем). Источник истины
для PostgreSQL — миграции Alembic.
"""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

logger = logging.getLogger("aios.db")


class Database:
    """Обёртка над async-движком и фабрикой сессий."""

    def __init__(self, settings) -> None:
        self.url = settings.database_url
        self.is_sqlite = self.url.startswith("sqlite")
        self.engine: AsyncEngine | None = None
        self.session_factory: async_sessionmaker[AsyncSession] | None = None

    def init_engine(self) -> None:
        """Создать движок и фабрику сессий, если ещё не созданы."""
        if self.engine is None:
            engine = create_async_engine(self.url, pool_pre_ping=True, future=True)
            if self.is_sqlite:
                # в SQLite нет схем — отображаем sales.* в основную БД
                engine = engine.execution_options(schema_translate_map={"sales": None})
            self.engine = engine
            self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

    async def connect(self) -> None:
        """Проверить соединение (Postgres) или создать таблицы (SQLite dev)."""
        self.init_engine()
        assert self.engine is not None

        if self.is_sqlite:
            import core.domain.models  # noqa: F401  — регистрация таблиц
            import modules.sales.models  # noqa: F401
            from core.db.base import Base

            async with self.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            logger.info("DB (sqlite dev): таблицы готовы (%s)", self.url)
        else:
            async with self.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            logger.info("DB: подключение успешно (%s)", self.url)

    async def disconnect(self) -> None:
        """Закрыть пул соединений (вызывается при остановке)."""
        if self.engine is not None:
            await self.engine.dispose()
            logger.info("DB: соединения закрыты")
