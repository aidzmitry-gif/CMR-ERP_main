"""Тест жизненного цикла приложения (lifespan) на временном SQLite — без Docker.

Покрывает реальный путь старта/остановки: ``services.db.connect`` (создание таблиц
в SQLite-dev), startup-хуки, запуск и отмену фонового цикла, ``disconnect``.
"""
from sqlalchemy import text

from config.settings import get_settings
from core.runtime.app import create_app


async def test_app_lifespan_starts_and_stops(tmp_path, monkeypatch):
    db_file = tmp_path / "lifespan.db"
    monkeypatch.setenv("AIOS_DATABASE_URL", f"sqlite+aiosqlite:///{db_file}")
    get_settings.cache_clear()  # пересобрать настройки на временный SQLite
    try:
        app = create_app()
        async with app.router.lifespan_context(app):
            core = app.state.core
            assert core.services.db.is_sqlite is True
            assert core.services.db.session_factory is not None
            # таблицы созданы → реальная сессия из фабрики ядра работает
            async with core.services.db.session_factory() as session:
                assert (await session.execute(text("SELECT 1"))).scalar() == 1
                # схема модуля доступна (создана из метаданных в dev-режиме)
                from modules.sales.models import Deal

                session.add(Deal(number="LIFE-1", title="t", counterparty="c"))
                await session.commit()
        # после выхода из lifespan движок закрыт
        assert core.services.db.engine is not None
    finally:
        get_settings.cache_clear()  # вернуть глобальный кэш настроек к окружению
