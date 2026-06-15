"""MDM — качество мастер-данных контрагентов в ядре (дедуп / merge / survivorship).

Сервисный слой shared kernel (НЕ отдельный модуль): живёт рядом с golden record в
``public``. Матчинг — детерминированный по УНП (natural key); fuzzy по имени — Postgres
``pg_trgm`` позже. **survivorship:** непустое значение выигрывает, эталон в приоритете при
конфликте. **merge обратим** (``unmerge``): дубль архивируется и ссылается на эталон, в
реестр пишется alias; расклейка возвращает дубль и убирает alias.

Транзакцию коммитит вызывающий код (роут) — здесь только изменения сессии (§ядро).
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.domain.models import Counterparty, CounterpartyAlias

#: поля контрагента, участвующие в survivorship при слиянии
_SURVIVORSHIP_FIELDS = ("name", "unp")


async def duplicate_clusters(session: AsyncSession) -> list[dict]:
    """Кластеры активных контрагентов с одинаковым УНП — кандидаты на слияние."""
    dup_unp_query = (
        select(Counterparty.unp)
        .where(Counterparty.is_active.is_(True), Counterparty.unp.is_not(None))
        .group_by(Counterparty.unp)
        .having(func.count() > 1)
    )
    unps = (await session.execute(dup_unp_query)).scalars().all()
    clusters: list[dict] = []
    for unp in unps:
        rows = (
            await session.execute(
                select(Counterparty)
                .where(Counterparty.unp == unp, Counterparty.is_active.is_(True))
                .order_by(Counterparty.id)
            )
        ).scalars().all()
        clusters.append(
            {"unp": unp, "members": [{"id": r.id, "name": r.name} for r in rows]}
        )
    return clusters


async def match_candidates(
    session: AsyncSession, *, unp: str | None, exclude_id: int | None = None
) -> list[Counterparty]:
    """Активные контрагенты с тем же УНП (детерминированный матч).

    Fuzzy-сопоставление по имени (опечатки/регистр) — через Postgres ``pg_trgm`` отдельной
    итерацией; здесь только точный natural key.
    """
    if not unp:
        return []
    query = select(Counterparty).where(
        Counterparty.unp == unp, Counterparty.is_active.is_(True)
    )
    if exclude_id is not None:
        query = query.where(Counterparty.id != exclude_id)
    return list((await session.execute(query)).scalars().all())


def _apply_survivorship(survivor: Counterparty, duplicate: Counterparty) -> None:
    """Непустое значение выигрывает; эталон в приоритете при конфликте (заполняем пустое)."""
    for field in _SURVIVORSHIP_FIELDS:
        if not getattr(survivor, field) and getattr(duplicate, field):
            setattr(survivor, field, getattr(duplicate, field))


async def merge(session: AsyncSession, survivor_id: int, duplicate_id: int) -> Counterparty:
    """Слить ``duplicate`` в ``survivor``: survivorship + архив дубля + alias. Обратимо."""
    if survivor_id == duplicate_id:
        raise ValueError("нельзя слить запись саму с собой")
    survivor = await session.get(Counterparty, survivor_id)
    duplicate = await session.get(Counterparty, duplicate_id)
    if survivor is None or duplicate is None:
        raise ValueError("контрагент не найден")
    if duplicate.merged_into_id is not None:
        raise ValueError("дубль уже слит")
    _apply_survivorship(survivor, duplicate)
    duplicate.is_active = False
    duplicate.merged_into_id = survivor_id
    session.add(
        CounterpartyAlias(counterparty_id=survivor_id, source="merge", external_ref=str(duplicate_id))
    )
    return survivor


async def unmerge(session: AsyncSession, duplicate_id: int) -> Counterparty:
    """Расклеить ранее слитый дубль: вернуть активность, снять ссылку, убрать merge-alias."""
    duplicate = await session.get(Counterparty, duplicate_id)
    if duplicate is None or duplicate.merged_into_id is None:
        raise ValueError("запись не является слитым дублем")
    alias = (
        await session.execute(
            select(CounterpartyAlias).where(
                CounterpartyAlias.source == "merge",
                CounterpartyAlias.external_ref == str(duplicate_id),
            )
        )
    ).scalars().first()
    if alias is not None:
        await session.delete(alias)
    duplicate.is_active = True
    duplicate.merged_into_id = None
    return duplicate


async def add_source_alias(
    session: AsyncSession, counterparty_id: int, source: str, external_ref: str
) -> CounterpartyAlias:
    """Привязать внешний идентификатор источника (1С/Bitrix) к эталону."""
    alias = CounterpartyAlias(
        counterparty_id=counterparty_id, source=source, external_ref=external_ref
    )
    session.add(alias)
    return alias


async def aliases(session: AsyncSession, counterparty_id: int) -> list[CounterpartyAlias]:
    """Все алиасы/источники эталонной записи."""
    return list(
        (
            await session.execute(
                select(CounterpartyAlias).where(
                    CounterpartyAlias.counterparty_id == counterparty_id
                )
            )
        ).scalars().all()
    )
