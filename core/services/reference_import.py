"""Идемпотентная загрузка мастер-данных контрагентов (входной адаптер, напр. 1С/Bitrix).

ERP — система-источник; внешняя система — **временный входной адаптер**. Сопоставление по
natural key (УНП): есть активный эталон — дополняем его и фиксируем внешний id как alias;
нет — создаём. **Идемпотентно:** повтор не плодит ни дублей контрагентов (матч по УНП), ни
дублей алиасов. Отключение источника = перестать звать этот сервис, структура не меняется.

Транзакцию коммитит вызывающий код (роут/sync-процесс модуля integrations).
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.domain.models import Counterparty, CounterpartyAlias
from core.services import mdm


@dataclass
class UpsertResult:
    counterparty: Counterparty
    created: bool
    alias_added: bool


async def _has_alias(
    session: AsyncSession, counterparty_id: int, source: str, external_ref: str
) -> bool:
    row = (
        await session.execute(
            select(CounterpartyAlias).where(
                CounterpartyAlias.counterparty_id == counterparty_id,
                CounterpartyAlias.source == source,
                CounterpartyAlias.external_ref == external_ref,
            )
        )
    ).scalars().first()
    return row is not None


async def upsert_counterparty(
    session: AsyncSession,
    *,
    unp: str,
    name: str | None,
    source: str = "1c",
    external_ref: str | None = None,
) -> UpsertResult:
    """Создать/сопоставить контрагента по УНП и зафиксировать внешний id как alias.

    Идемпотентно: повторный вызов с теми же данными не создаёт ни дубль контрагента,
    ни дубль алиаса. Существующее имя НЕ перезатирается (только заполняем пустое).
    """
    if not unp:
        raise ValueError("нужен УНП (natural key)")
    candidates = await mdm.match_candidates(session, unp=unp)
    created = False
    if candidates:
        counterparty = candidates[0]
        if not counterparty.name and name:
            counterparty.name = name
    else:
        counterparty = Counterparty(name=name or "", unp=unp)
        session.add(counterparty)
        await session.flush()  # получить id для alias
        created = True

    alias_added = False
    if external_ref and not await _has_alias(session, counterparty.id, source, external_ref):
        await mdm.add_source_alias(session, counterparty.id, source, external_ref)
        alias_added = True
    return UpsertResult(counterparty, created, alias_added)


async def import_counterparties(session: AsyncSession, rows: list[dict], *, source: str = "1c") -> dict:
    """Пакетный идемпотентный импорт. ``rows``: список ``{unp, name, external_ref|id}``.

    Возвращает сводку для предпросмотра/лога адаптера.
    """
    created = matched = aliased = 0
    for row in rows:
        result = await upsert_counterparty(
            session,
            unp=row.get("unp"),
            name=row.get("name"),
            source=source,
            external_ref=row.get("external_ref") or row.get("id"),
        )
        if result.created:
            created += 1
        else:
            matched += 1
        if result.alias_added:
            aliased += 1
    return {"total": len(rows), "created": created, "matched": matched, "aliases_added": aliased}
