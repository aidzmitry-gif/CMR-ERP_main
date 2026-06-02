"""Фикстуры тестов.

БД-зависимые тесты гоняем на SQLite в памяти (без Postgres): схемы модулей
(`sales`) маппим в схему по умолчанию через ``schema_translate_map``. Запросы
делаем через httpx ASGITransport в том же event loop, что и сессия, — чтобы
async-драйвер sqlite не ругался на «другой loop».
"""
from __future__ import annotations

import importlib

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


@pytest_asyncio.fixture
async def api(session):
    app = create_app()

    async def _override():
        yield session

    app.dependency_overrides[get_session] = _override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
