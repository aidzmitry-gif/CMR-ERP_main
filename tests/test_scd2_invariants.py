"""Круг 5 харднинг — инварианты SCD2 (ядро датированных версий справочников).

Закрепляем ТЕКУЩЕЕ корректное поведение `core.services.scd2`: новая версия закрывает
предыдущую, после серии правок ровно ОДНА открытая (`end_date IS NULL`), интервал
полуоткрытый, нельзя открыть версию не позже текущей.

⚠ INFO (NEEDS-ARB круга 2, не закрыт): на уровне БД НЕТ partial-unique индекса
`WHERE end_date IS NULL` — единственность открытой версии держится прикладной проверкой
`add_version` (читает current_version перед вставкой). Две ПАРАЛЛЕЛЬНЫЕ транзакции на общих
таблицах (currency/vat/tnved/sku_version) теоретически могут открыть две версии (гонка) —
координированная миграция отложена (blast radius). Тесты ниже фиксируют последовательный
инвариант; гонку не воспроизводим (нужен индекс).
"""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from core.domain.reference import VatRate
from core.services import scd2


async def _open_versions(session, key: str) -> list:
    return (
        await session.execute(
            select(VatRate).where(VatRate.code == key, VatRate.end_date.is_(None))
        )
    ).scalars().all()


async def test_new_version_closes_previous(session):
    await scd2.add_version(session, VatRate, "code", "Н", date(2020, 1, 1), title="x", rate=Decimal("20"))
    await scd2.add_version(session, VatRate, "code", "Н", date(2024, 1, 1), title="x", rate=Decimal("25"))
    await session.commit()
    rows = (
        await session.execute(
            select(VatRate).where(VatRate.code == "Н").order_by(VatRate.start_date)
        )
    ).scalars().all()
    assert len(rows) == 2
    assert rows[0].end_date == date(2024, 1, 1)  # старая закрыта датой новой (полуоткрытый интервал)
    assert rows[1].end_date is None  # новая — текущая


async def test_exactly_one_open_after_series(session):
    for i, yr in enumerate((2020, 2021, 2022, 2023)):
        await scd2.add_version(
            session, VatRate, "code", "К", date(yr, 1, 1), title="x", rate=Decimal(str(10 + i))
        )
    await session.commit()
    assert len(await _open_versions(session, "К")) == 1  # ровно одна открытая после серии


async def test_add_version_rejects_non_increasing_start(session):
    await scd2.add_version(session, VatRate, "code", "Z", date(2024, 1, 1), title="x", rate=Decimal("20"))
    with pytest.raises(ValueError):  # та же дата, что у открытой
        await scd2.add_version(session, VatRate, "code", "Z", date(2024, 1, 1), title="x", rate=Decimal("21"))
    with pytest.raises(ValueError):  # раньше открытой
        await scd2.add_version(session, VatRate, "code", "Z", date(2023, 1, 1), title="x", rate=Decimal("22"))


async def test_version_as_of_picks_right_interval(session):
    await scd2.add_version(session, VatRate, "code", "AS", date(2020, 1, 1), title="x", rate=Decimal("20"))
    await scd2.add_version(session, VatRate, "code", "AS", date(2024, 1, 1), title="x", rate=Decimal("25"))
    await session.commit()
    assert await scd2.version_as_of(session, VatRate, "code", "AS", date(2019, 1, 1)) is None  # до первой
    v_old = await scd2.version_as_of(session, VatRate, "code", "AS", date(2022, 1, 1))
    assert v_old.rate == Decimal("20")
    v_new = await scd2.version_as_of(session, VatRate, "code", "AS", date(2025, 1, 1))
    assert v_new.rate == Decimal("25")
    # граница интервала: дата начала новой версии принадлежит ей (start <= on), старая закрыта
    v_boundary = await scd2.version_as_of(session, VatRate, "code", "AS", date(2024, 1, 1))
    assert v_boundary.rate == Decimal("25")
