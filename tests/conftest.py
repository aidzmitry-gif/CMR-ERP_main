"""Фикстуры тестов.

БД-зависимые тесты гоняем на SQLite в памяти (без Postgres): схемы модулей
(`sales`) маппим в схему по умолчанию через ``schema_translate_map``. Запросы
делаем через httpx ASGITransport в том же event loop, что и сессия, — чтобы
async-драйвер sqlite не ругался на «другой loop».
"""
from __future__ import annotations

import asyncio
import importlib
import os
import sys
from pathlib import Path
from uuid import uuid4

# psycopg async cannot run on Windows' default ProactorEventLoop.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Тесты — не прод: dev-режим, чтобы прод-guard (SECURITY.md P0-5) не падал на
# dev-кредах БД из .env. Выставить ДО импорта core.runtime.app (тянет настройки).
os.environ.setdefault("AIOS_ENVIRONMENT", "dev")

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import core.domain.models  # noqa: F401  — регистрация таблиц на Base.metadata
from config.modules import ENABLED_MODULES
from core.db.base import Base
from core.runtime.app import create_app
from core.runtime.deps import get_session

for _module in ENABLED_MODULES:
    try:
        importlib.import_module(f"modules.{_module}.models")
    except ModuleNotFoundError:
        pass

SCHEMA_TRANSLATE = {module: None for module in ENABLED_MODULES}


@pytest.fixture
def tmp_path() -> Path:
    """Sandbox-friendly tmp path: create unique dirs without teardown cleanup."""
    root = Path(".tmp_pytest/manual")
    root.mkdir(parents=True, exist_ok=True)
    path = root / uuid4().hex
    path.mkdir()
    return path


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    engine = engine.execution_options(schema_translate_map=SCHEMA_TRANSLATE)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


# Дефолт-роль функциональных API-фикстур. После fail-closed (SECURITY.md P0-1) запрос без
# роли — бесправный «Гость» (403). Исторически фикстура `api` означала «авторизованный
# клиент» (неявный дефолт-Админ), поэтому ставим супер-роль явно. Тесты доступа, шлющие свой
# `X-User-Roles`, переопределяют этот дефолт на уровне запроса (per-request > client default).
AUTHED_HEADERS = {"X-User-Roles": "director"}


@pytest_asyncio.fixture
async def api(session):
    app = create_app()

    async def _override():
        yield session

    app.dependency_overrides[get_session] = _override
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", headers=AUTHED_HEADERS
    ) as client:
        yield client


@pytest_asyncio.fixture
async def ai_api(session):
    """API-клиент с включённым AI-слоем (mock-режим шлюза) — для AI-эндпоинтов."""
    app = create_app()

    async def _override():
        yield session

    app.dependency_overrides[get_session] = _override
    app.state.core.services.llm.enabled = True  # включить feature-flag AI для теста
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", headers=AUTHED_HEADERS
    ) as client:
        yield client


@pytest_asyncio.fixture
async def api_no_gateways(session):
    """API-клиент с отключёнными шлюзами 1С/склад/ЕГР — для защитных 503-веток."""
    app = create_app()

    async def _override():
        yield session

    app.dependency_overrides[get_session] = _override
    core = app.state.core
    core.services.onec = None
    core.services.stock = None
    core.services.registry = None
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", headers=AUTHED_HEADERS
    ) as client:
        yield client


@pytest_asyncio.fixture
async def services(session):
    """Сервисы загруженного приложения (event_bus, stock, …) — для прямого вызова
    фоновых шагов (``core.on_tick``) в тестах. Операции идут над тест-сессией ``session``."""
    app = create_app()
    return app.state.core.services


def pytest_collection_modifyitems(items) -> None:
    """Авто-маркировка по слою пирамиды: tests/unit → unit, integration → integration, прочее → api."""
    for item in items:
        path = str(item.fspath).replace("\\", "/")
        if "/tests/unit/" in path:
            item.add_marker("unit")
        elif "/tests/integration/" in path:
            item.add_marker("integration")
        else:
            item.add_marker("api")
