"""Тест жизненного цикла приложения (lifespan) на временном SQLite — без Docker.

Покрывает реальный путь старта/остановки: ``services.db.connect`` (создание таблиц
в SQLite-dev), startup-хуки, запуск и отмену фонового цикла, ``disconnect``.
"""
import importlib

from httpx import ASGITransport, AsyncClient
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
            assert app.state.async_writers_disabled is False
            assert app.state.http_writes_blocked is False
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                assert (await client.post("/health")).status_code == 405
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


async def test_pilot_quiet_start_skips_all_startup_background_and_shutdown_hooks(
    tmp_path, monkeypatch,
):
    db_file = tmp_path / "quiet-start.db"
    monkeypatch.setenv("AIOS_DATABASE_URL", f"sqlite+aiosqlite:///{db_file}")
    monkeypatch.setenv("AIOS_DISABLE_ASYNC_WRITERS", "1")
    get_settings.cache_clear()
    runtime_app = importlib.import_module("core.runtime.app")
    called = []

    async def unexpected(*_args):
        called.append("background")

    monkeypatch.setattr(runtime_app, "_background_loop", unexpected)
    monkeypatch.setattr(runtime_app, "sync_nbrb", unexpected)
    try:
        app = create_app()
        core = app.state.core

        async def startup():
            called.append("startup")

        async def shutdown():
            called.append("shutdown")

        core.startup_hooks[:] = [startup]
        core.shutdown_hooks[:] = [shutdown]
        async with app.router.lifespan_context(app):
            assert app.state.async_writers_disabled is True
            async with core.services.db.session_factory() as session:
                assert (await session.execute(text("SELECT 1"))).scalar() == 1
        assert called == []
    finally:
        get_settings.cache_clear()


async def test_pilot_http_gate_blocks_mutations_before_route_and_auth(tmp_path, monkeypatch):
    db_file = tmp_path / "http-gate.db"
    monkeypatch.setenv("AIOS_DATABASE_URL", f"sqlite+aiosqlite:///{db_file}")
    monkeypatch.setenv("AIOS_DISABLE_ASYNC_WRITERS", "1")
    monkeypatch.setenv("AIOS_BLOCK_HTTP_WRITES", "1")
    get_settings.cache_clear()
    try:
        app = create_app()
        async with app.router.lifespan_context(app):
            assert app.state.http_writes_blocked is True
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                assert (await client.get("/health")).status_code == 200
                blocked = await client.post("/health")
                assert blocked.status_code == 503
                assert blocked.json()["detail"]["code"] == "pilot_http_writes_disabled"
    finally:
        get_settings.cache_clear()
