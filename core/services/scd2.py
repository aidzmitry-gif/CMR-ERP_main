"""SCD Type 2 — датированные версии справочников (курс валюты, ставка НДС, прайс).

Полуоткрытый интервал ``[start_date, end_date)``; текущая версия — ``end_date IS NULL``.
Версии не перезаписываются: новая открывается с даты, предыдущая закрывается этой же датой
(без перекрытий и зазоров). Документ «на дату» видит ровно одну версию.

Транзакцию коммитит вызывающий код (роут/workflow) — здесь только изменения сессии,
как принято в ядре (репозитории/сервисы не коммитят).
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession


async def current_version(session: AsyncSession, model: type, key_field: str, key_value):
    """Текущая (открытая) версия для natural key — та, где ``end_date IS NULL``."""
    key = getattr(model, key_field)
    query = select(model).where(key == key_value, model.end_date.is_(None))
    return (await session.execute(query)).scalars().first()


async def version_as_of(session: AsyncSession, model: type, key_field: str, key_value, on: date):
    """Версия, действовавшая на дату ``on``: ``start_date <= on < end_date`` (или end открыт)."""
    key = getattr(model, key_field)
    query = select(model).where(
        key == key_value,
        model.start_date <= on,
        or_(model.end_date.is_(None), model.end_date > on),
    )
    return (await session.execute(query)).scalars().first()


async def add_version(
    session: AsyncSession, model: type, key_field: str, key_value, start: date, **values
):
    """Открыть новую версию с даты ``start``: закрыть текущую (``end_date = start``), вставить новую.

    Бросает ``ValueError``, если новая версия не позже текущей открытой (защита от перекрытия).
    Не коммитит — это делает вызывающий роут.
    """
    open_row = await current_version(session, model, key_field, key_value)
    if open_row is not None:
        if start <= open_row.start_date:
            raise ValueError("новая версия должна начинаться позже текущей открытой версии")
        open_row.end_date = start
    new_row = model(**{key_field: key_value, "start_date": start, "end_date": None, **values})
    session.add(new_row)
    return new_row
