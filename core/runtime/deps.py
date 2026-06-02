"""FastAPI-зависимости ядра."""
from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from core.runtime.core import Core


def get_core(request: Request) -> Core:
    """Достать экземпляр ядра из состояния приложения."""
    return request.app.state.core


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Выдать async-сессию БД на время запроса."""
    db = request.app.state.core.services.db
    if db.session_factory is None:
        db.init_engine()
    assert db.session_factory is not None
    async with db.session_factory() as session:
        yield session
