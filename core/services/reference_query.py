"""Структурный доступ AI к справочникам — backend для tool ``reference.query``.

Semantic-слой исполнения. AI/агент по каталогу (``/system/references/ai-catalog``) знает
«что есть и как точно запросить», а сюда шлёт структурный запрос и получает **точное
значение** — с историчностью (``as_of``), а не эмбеддинг. pgvector — вторично (нечёткий
поиск имён/дедуп), отдельной итерацией.

Только чтение: транзакцию не меняем.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.domain.models import Counterparty, Sku
from core.domain.reference import Bank, Country, Currency, CurrencyRate, Unit, VatRate
from core.services import scd2


class ReferenceQueryError(ValueError):
    """Некорректный запрос: неизвестный ``ref`` или не хватает параметров."""


# простые справочники: ref -> (model, поля)
_SIMPLE = {
    "core.units": (Unit, ("code", "title", "is_active")),
    "core.currencies": (Currency, ("code", "title", "is_active")),
    "core.countries": (Country, ("code", "title", "is_active")),
    "core.banks": (Bank, ("code", "title", "swift", "is_active")),
}
# версионные (SCD2): ref -> (model, natural key, поля)
_VERSIONED = {
    "core.currency_rates": (
        CurrencyRate,
        "currency_code",
        ("currency_code", "rate", "start_date", "end_date"),
    ),
    "core.vat_rates": (VatRate, "code", ("code", "title", "rate", "start_date", "end_date")),
}


def _row(obj, fields: tuple[str, ...]) -> dict:
    return {f: getattr(obj, f) for f in fields}


async def query(
    session: AsyncSession,
    ref: str,
    *,
    key: str | None = None,
    as_of: date | None = None,
    name: str | None = None,
    limit: int = 10,
) -> dict:
    """Структурный lookup по справочнику ``ref`` — возвращает точное значение(я).

    - простые (``core.units``/...): ``key``=code → запись; без key → список активных;
    - версионные (``core.currency_rates``/``core.vat_rates``): ``key`` + ``as_of`` → версия,
      действовавшая на дату (или текущая без ``as_of``), с периодом ``start_date/end_date``;
    - ``core.counterparties``: ``key``=УНП или ``name`` → эталоны (active, не слитые);
    - ``core.skus``: ``key``=code → позиция номенклатуры.
    """
    if ref in _SIMPLE:
        return await _query_simple(session, ref, key, limit)
    if ref in _VERSIONED:
        return await _query_versioned(session, ref, key, as_of)
    if ref == "core.counterparties":
        return await _query_counterparties(session, key, name, limit)
    if ref == "core.skus":
        return await _query_skus(session, key, limit)
    raise ReferenceQueryError(f"неизвестный справочник: {ref}")


async def _query_simple(session: AsyncSession, ref: str, key: str | None, limit: int) -> dict:
    model, fields = _SIMPLE[ref]
    stmt = select(model).where(model.is_active.is_(True))
    if key is not None:
        stmt = stmt.where(model.code == key)
    rows = (await session.execute(stmt.order_by(model.code).limit(limit))).scalars().all()
    if key is not None:
        return {"ref": ref, "key": key, "result": _row(rows[0], fields) if rows else None}
    return {"ref": ref, "result": [_row(r, fields) for r in rows]}


async def _query_versioned(
    session: AsyncSession, ref: str, key: str | None, as_of: date | None
) -> dict:
    if not key:
        raise ReferenceQueryError(f"{ref}: нужен параметр key (natural key)")
    model, key_field, fields = _VERSIONED[ref]
    if as_of is not None:
        obj = await scd2.version_as_of(session, model, key_field, key, as_of)
    else:
        obj = await scd2.current_version(session, model, key_field, key)
    return {
        "ref": ref,
        "key": key,
        "as_of": as_of,
        "result": _row(obj, fields) if obj is not None else None,
    }


async def _query_counterparties(
    session: AsyncSession, key: str | None, name: str | None, limit: int
) -> dict:
    stmt = select(Counterparty).where(
        Counterparty.is_active.is_(True), Counterparty.merged_into_id.is_(None)
    )
    if key:
        stmt = stmt.where(Counterparty.unp == key)
    elif name:
        stmt = stmt.where(Counterparty.name.ilike(f"%{name}%"))
    else:
        raise ReferenceQueryError("core.counterparties: нужен key (УНП) или name")
    rows = (await session.execute(stmt.limit(limit))).scalars().all()
    return {
        "ref": "core.counterparties",
        "result": [{"id": r.id, "name": r.name, "unp": r.unp} for r in rows],
    }


async def _query_skus(session: AsyncSession, key: str | None, limit: int) -> dict:
    stmt = select(Sku)
    if key:
        stmt = stmt.where(Sku.code == key)
    rows = (await session.execute(stmt.limit(limit))).scalars().all()
    return {
        "ref": "core.skus",
        "result": [{"code": r.code, "title": r.title, "unit": r.unit} for r in rows],
    }
