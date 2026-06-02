"""Доступ к БД: async SQLAlchemy 2 поверх psycopg3 (PostgreSQL 16 + pgvector).

Движок создаётся лениво (`init_engine`) и проверяется при старте приложения
(`connect`). Таблица outbox для событий появится в части 3.
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
        self.engine: AsyncEngine | None = None
        self.session_factory: async_sessionmaker[AsyncSession] | None = None

    def init_engine(self) -> None:
        """Создать движок и фабрику сессий, если ещё не созданы."""
        if self.engine is None:
            self.engine = create_async_engine(self.url, pool_pre_ping=True, future=True)
            self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

    async def connect(self) -> None:
        """Проверить соединение с БД (вызывается при старте)."""
        self.init_engine()
        assert self.engine is not None
        async with self.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("DB: подключение успешно (%s)", self.url)

    async def disconnect(self) -> None:
        """Закрыть пул соединений (вызывается при остановке)."""
        if self.engine is not None:
            await self.engine.dispose()
            logger.info("DB: соединения закрыты")
