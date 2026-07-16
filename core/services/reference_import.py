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
from core.services import mdm, survivorship
from core.services.survivorship import FieldValue, Rule, is_empty

#: поля контрагента, к которым применяется survivorship при импорте (имя — единственное
#: мастер-поле модели сейчас; расширяется вместе с моделью).
_IMPORT_FIELDS = ("name",)


@dataclass
class UpsertResult:
    counterparty: Counterparty
    created: bool
    alias_added: bool
    updated_fields: tuple[str, ...] = ()  # какие поля синк реально изменил (по правилам)


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


def _apply_field(
    cp: Counterparty, field: str, incoming, source: str, at: str | None, rule: Rule
) -> bool:
    """Применить survivorship-правило к одному полю; обновить provenance. True — поле изменилось."""
    current = None
    if not is_empty(getattr(cp, field)):
        prov = (cp.provenance or {}).get(field, {})
        current = FieldValue(getattr(cp, field), prov.get("source", "1c"), prov.get("at"))
    winner = survivorship.decide(current, FieldValue(incoming, source, at), rule)
    changed = winner.value != getattr(cp, field)
    if changed:
        setattr(cp, field, winner.value)
    # provenance отражает источник победителя (фиксируем «кто владеет полем»)
    prov = dict(cp.provenance or {})
    prov[field] = {"source": winner.source, "at": winner.at}
    cp.provenance = prov
    return changed


async def upsert_counterparty(
    session: AsyncSession,
    *,
    unp: str,
    name: str | None,
    source: str = "1c",
    external_ref: str | None = None,
    at: str | None = None,
    rules: dict[str, Rule] | None = None,
) -> UpsertResult:
    """Создать/сопоставить контрагента по УНП, применить survivorship-правила, зафиксировать alias.

    Идемпотентно: повтор не плодит ни дублей, ни алиасов. Поля обновляются **по правилам
    слияния** (``survivorship_rule``), а не «непустое в пустое»: синк из 1С не затирает то,
    что закреплено за ЕГР/ERP/ручным вводом. Источник каждого поля пишется в ``provenance``.
    ``at`` — дата значения из источника (ISO) для стратегии ``most_recent``. ``rules`` можно
    передать предзагруженными (батч), иначе грузятся здесь.
    """
    if not unp:
        raise ValueError("нужен УНП (natural key)")
    if rules is None:
        rules = await survivorship.load_rules(session, "counterparty")
    candidates = await mdm.match_candidates(session, unp=unp)
    created = False
    updated: list[str] = []
    incoming = {"name": name}
    if candidates:
        counterparty = candidates[0]
        for field in _IMPORT_FIELDS:
            val = incoming.get(field)
            if val is None:
                continue
            if _apply_field(
                counterparty, field, val, source, at, survivorship.rule_for(rules, field)
            ):
                updated.append(field)
    else:
        counterparty = Counterparty(name=name or "", unp=unp)
        counterparty.provenance = {
            f: {"source": source, "at": at}
            for f in _IMPORT_FIELDS
            if incoming.get(f) is not None
        }
        session.add(counterparty)
        await session.flush()  # получить id для alias
        created = True

    alias_added = False
    if external_ref and not await _has_alias(session, counterparty.id, source, external_ref):
        await mdm.add_source_alias(session, counterparty.id, source, external_ref)
        alias_added = True
    return UpsertResult(counterparty, created, alias_added, tuple(updated))


async def import_counterparties(session: AsyncSession, rows: list[dict], *, source: str = "1c") -> dict:
    """Пакетный идемпотентный импорт. ``rows``: список ``{unp, name, external_ref|id}``.

    Возвращает сводку для предпросмотра/лога адаптера.
    Строки без УНП пропускаются (в 1С бывают группы/элементы без ИНН) — иначе батч
    падает на ``upsert_counterparty`` и остатки/SKU не доезжают.
    """
    created = matched = aliased = skipped = 0
    rules = await survivorship.load_rules(session, "counterparty")  # один раз на батч
    for row in rows:
        unp = (row.get("unp") or "").strip()
        if not unp:
            skipped += 1
            continue
        result = await upsert_counterparty(
            session,
            unp=unp,
            name=row.get("name"),
            source=source,
            external_ref=row.get("external_ref") or row.get("id"),
            rules=rules,
        )
        if result.created:
            created += 1
        else:
            matched += 1
        if result.alias_added:
            aliased += 1
    return {
        "total": len(rows),
        "created": created,
        "matched": matched,
        "aliases_added": aliased,
        "skipped_no_unp": skipped,
    }
