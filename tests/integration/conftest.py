"""Фикстуры integration-слоя пирамиды: реальный PostgreSQL.

Проверяют связку FastAPI + PostgreSQL целиком — реальные ``get_session``,
``db.connect/disconnect``, схемы из миграций Alembic, фоновый relay. Источник БД:
готовый Postgres из ``AIOS_DATABASE_URL`` (как в CI-сервисе) или поднятый на лету
контейнер (testcontainers, нужен Docker). Если нет ни того, ни другого — пропуск.
"""
from __future__ import annotations

import os
import subprocess

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from config.settings import get_settings


def _docker_available() -> bool:
    try:
        import docker  # поставляется с testcontainers

        docker.from_env().ping()
        return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def postgres_url():
    """URL реального Postgres: из окружения (CI-сервис) или из контейнера testcontainers."""
    env_url = os.environ.get("AIOS_DATABASE_URL", "")
    if env_url.startswith("postgresql"):
        # CI: сервис уже поднят и мигрирован (alembic upgrade head в workflow)
        yield env_url
        return
    if not _docker_available():
        pytest.skip("Нет Postgres (AIOS_DATABASE_URL) и Docker недоступен — integration пропущены")

    from testcontainers.postgres import PostgresContainer

    with PostgresContainer(
        "pgvector/pgvector:pg16", driver="psycopg", username="aios", password="aios", dbname="aios"
    ) as pg:
        url = pg.get_connection_url()  # postgresql+psycopg://aios:aios@host:port/aios
        subprocess.run(
            ["alembic", "upgrade", "head"],
            check=True,
            env={**os.environ, "AIOS_DATABASE_URL": url},
        )
        yield url


@pytest_asyncio.fixture
async def pg_app(postgres_url, monkeypatch):
    """Клиент приложения на реальном Postgres с РЕАЛЬНОЙ ``get_session`` (без подмены)."""
    monkeypatch.setenv("AIOS_DATABASE_URL", postgres_url)
    get_settings.cache_clear()  # пересобрать настройки на Postgres-URL
    from core.runtime.app import create_app

    app = create_app()
    await app.state.core.services.db.connect()  # реальное подключение к Postgres
    transport = ASGITransport(app=app)
    # fail-closed RBAC (SECURITY.md P0-1): запрос без роли — «Гость» (403). Шлём супер-роль
    # по умолчанию, как SQLite-фикстура `api` (tests/conftest.py::AUTHED_HEADERS).
    try:
        async with AsyncClient(
            transport=transport, base_url="http://test", headers={"X-User-Roles": "director"}
        ) as client:
            yield client
    finally:
        await app.state.core.services.db.disconnect()
        get_settings.cache_clear()
