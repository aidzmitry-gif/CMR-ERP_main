"""Идемпотентная загрузка мастер-данных контрагентов (входной адаптер, напр. 1С/Bitrix).

ERP — система-источник; внешняя система — **временный входной адаптер**. Сопоставление по
Сначала используется точный alias источника, затем единственный активный УНП;
неоднозначность останавливает импорт. **Идемпотентно:** повтор не плодит ни дублей контрагентов, ни
дублей алиасов. Отключение источника = перестать звать этот сервис, структура не меняется.

Транзакцию коммитит вызывающий код (роут/sync-процесс модуля integrations).
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import blake2b

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from core.domain.models import (
    Counterparty,
    CounterpartyAlias,
    CounterpartyBranchAlias,
    lock_counterparty_unps,
)
from core.services import mdm, survivorship
from core.services.survivorship import FieldValue, Rule, is_empty

#: Legacy name fills only an empty value; legal name uses explicit source rules.
_IMPORT_FIELDS = ("name", "legal_name")


async def _lock_alias_refs(session: AsyncSession, source: str, refs: set[str]) -> None:
    if session.bind.dialect.name == "postgresql":
        for ref in sorted(refs):
            digest = blake2b(f"counterparty-alias:{source}:{ref}".encode(), digest_size=8).digest()
            await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": int.from_bytes(digest, "big", signed=True)})


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
    prov[field] = {
        **(prov.get(field, {}) if winner is current else {}),
        "source": winner.source, "at": winner.at,
    }
    cp.provenance = prov
    return changed


async def upsert_counterparty(
    session: AsyncSession,
    *,
    unp: str,
    name: str | None,
    legal_name: str | None = None,
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
    if legal_name is not None and len(legal_name) > 255:
        raise mdm.CounterpartyWriteError("invalid_legal_name", "Юридическое наименование превышает 255 символов; импорт остановлен без обрезки", 422)
    if rules is None:
        rules = await survivorship.load_rules(session, "counterparty")
    await session.run_sync(lambda sync: lock_counterparty_unps(sync, {unp}))
    alias = None
    if external_ref:
        await _lock_alias_refs(session, source, {external_ref})
        if await session.scalar(select(CounterpartyBranchAlias.id).where(
            CounterpartyBranchAlias.source == source, CounterpartyBranchAlias.external_ref == external_ref,
        )) is not None:
            raise mdm.CounterpartyWriteError("source_kind_conflict", "ID источника уже принадлежит филиалу")
        alias = (await session.scalars(select(CounterpartyAlias).where(
            CounterpartyAlias.source == source, CounterpartyAlias.external_ref == external_ref,
        ))).one_or_none()
    if alias:
        linked = await session.get(Counterparty, alias.counterparty_id)
        target_id = linked.merged_into_id or linked.id
        locked = list(await session.scalars(select(Counterparty).where(
            Counterparty.id.in_({linked.id, target_id}),
        ).order_by(Counterparty.id).with_for_update().execution_options(populate_existing=True)))
        by_id = {cp.id: cp for cp in locked}
        linked = by_id[alias.counterparty_id]
        counterparty = by_id.get(linked.merged_into_id or linked.id)
        if counterparty is None:
            raise mdm.CounterpartyWriteError("source_identity_changed", "Связь источника изменена параллельно; повторите импорт")
        if not counterparty.is_active or counterparty.merged_into_id is not None or counterparty.unp != unp:
            raise mdm.CounterpartyWriteError("source_identity_conflict", "Внешний ID связан с другим УНП или архивным контрагентом")
        candidates = [counterparty]
    else:
        candidates = list(await session.scalars(select(Counterparty).where(
            Counterparty.unp == unp, Counterparty.is_active.is_(True), Counterparty.merged_into_id.is_(None),
        ).order_by(Counterparty.id).with_for_update().execution_options(populate_existing=True)))
        if len(candidates) > 1:
            raise mdm.CounterpartyWriteError("ambiguous_unp", "Несколько активных контрагентов с одним УНП; требуется явное сопоставление")
    created = False
    updated: list[str] = []
    incoming = {"name": name, "legal_name": legal_name}
    if candidates:
        counterparty = candidates[0]
        for field in _IMPORT_FIELDS:
            val = incoming.get(field)
            if val is None:
                continue
            # Existing working/legacy names and manually confirmed legal names are not import targets.
            if field == "name" and not is_empty(counterparty.name):
                continue
            if field == "legal_name" and (counterparty.provenance or {}).get(field, {}).get("source") in {"manual", "mns_grp"}:
                continue
            rule = survivorship.rule_for(rules, "name" if field == "legal_name" and field not in rules else field)
            if rule.strategy == "manual_only" and source != "manual":
                continue
            if _apply_field(
                counterparty, field, val, source, at,
                rule,
            ):
                updated.append(field)
    else:
        rule = survivorship.rule_for(rules, "legal_name" if "legal_name" in rules else "name")
        if rule.strategy == "manual_only" and source != "manual":
            legal_name = None
            incoming["legal_name"] = None
        counterparty = Counterparty(name=name or legal_name or "", legal_name=legal_name, unp=unp)
        counterparty.provenance = {
            f: {"source": source, "at": at}
            for f in _IMPORT_FIELDS
            if incoming.get(f) is not None
        }
        session.add(counterparty)
        await session.flush()  # получить id для alias
        created = True

    alias_added = False
    if external_ref and alias is None and not await _has_alias(session, counterparty.id, source, external_ref):
        await mdm.add_source_alias(session, counterparty.id, source, external_ref)
        alias_added = True
    return UpsertResult(counterparty, created, alias_added, tuple(updated))


async def import_counterparties(session: AsyncSession, rows: list[dict], *, source: str = "1c") -> dict:
    """Пакетный идемпотентный импорт. ``rows``: список ``{unp, name, external_ref|id}``.

    Возвращает сводку для предпросмотра/лога адаптера.
    Строки без УНП пропускаются (в 1С бывают группы/элементы без ИНН) — иначе батч
    падает на ``upsert_counterparty`` и остатки/SKU не доезжают.
    """
    for row in rows:
        if row.get("record_kind") not in (None, "head", "branch"):
            raise mdm.CounterpartyWriteError("invalid_record_kind", "Неизвестный тип записи источника", 422)
        if row.get("record_kind") != "branch" and row.get("parent_external_ref") is not None:
            raise mdm.CounterpartyWriteError("branch_mapping_required", "Связь с головным предприятием допустима только для филиала", 422)
    if any(row.get("record_kind") == "branch" for row in rows):
        from core.services.reference_branch_import import import_branch_batch

        return await import_branch_batch(session, rows, source=source)
    created = matched = aliased = skipped = 0
    # One transaction keeps locks until the whole batch commits: take the complete sets in order.
    unps = {(row.get("unp") or "").strip() for row in rows} - {""}
    refs = {row.get("external_ref") or row.get("id") for row in rows if (row.get("unp") or "").strip()}
    await session.run_sync(lambda sync: lock_counterparty_unps(sync, unps))
    await _lock_alias_refs(session, source, {ref for ref in refs if ref})
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
            legal_name=row.get("legal_name"),
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
