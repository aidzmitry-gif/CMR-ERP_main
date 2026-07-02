"""Integration-тест на реальном PostgreSQL: partial-unique индекс SCD2 (миграция 0084).

Проверяет то, что SQLite-контур не может (там схема из ORM ``create_all``, партиального
индекса нет): БД САМА отклоняет вторую открытую (``end_date IS NULL``) версию по тому же
natural key. Это моделирует гонку двух параллельных транзакций, которые обе не увидели
открытую версию друг друга и обе сделали INSERT в обход прикладной проверки
``scd2.add_version``.

Прогоняется только когда доступен Postgres (``AIOS_DATABASE_URL`` CI-сервиса или Docker для
testcontainers) — иначе фикстура ``postgres_url`` делает skip. Схема на контейнере уже
мигрирована до head (``alembic upgrade head`` в фикстуре) → индекс ``uq_ref_vat_rate_open``
присутствует.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.domain.reference import VatRate


async def test_second_open_version_rejected_by_db(postgres_url):
    """Вторая открытая версия по тому же ключу → IntegrityError от partial-unique индекса."""
    engine = create_async_engine(postgres_url, future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as s:
            s.add(VatRate(code="RACE", title="v1", rate=Decimal("20"),
                          start_date=date(2020, 1, 1), end_date=None))
            await s.flush()
            # Вторая открытая версия того же ключа — прямой INSERT в обход add_version.
            s.add(VatRate(code="RACE", title="v2", rate=Decimal("25"),
                          start_date=date(2024, 1, 1), end_date=None))
            with pytest.raises(IntegrityError):
                await s.flush()
            await s.rollback()
    finally:
        await engine.dispose()


async def test_closed_plus_open_version_allowed(postgres_url):
    """Закрытая (end_date задан) + открытая версия того же ключа разрешены — предикат partial."""
    engine = create_async_engine(postgres_url, future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as s:
            s.add(VatRate(code="HIST", title="old", rate=Decimal("18"),
                          start_date=date(2018, 1, 1), end_date=date(2020, 1, 1)))
            s.add(VatRate(code="HIST", title="cur", rate=Decimal("20"),
                          start_date=date(2020, 1, 1), end_date=None))
            await s.flush()  # обе строки проходят: под предикат WHERE end_date IS NULL — одна
            await s.rollback()
    finally:
        await engine.dispose()
