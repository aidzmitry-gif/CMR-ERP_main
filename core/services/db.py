"""Доступ к БД (PostgreSQL 16 + pgvector). Заглушка до части 2.

В части 2 здесь появятся SQLAlchemy 2 engine/session и репозитории доменной
модели; в части 3 — таблица outbox для событий.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("aios.db")


class Database:
    """Заглушка доступа к БД. Хранит URL, движок появится в части 2."""

    def __init__(self, settings) -> None:
        self.url = settings.database_url
        self.engine = None

    async def connect(self) -> None:
        logger.info("DB: заглушка (engine появится в части 2): %s", self.url)
