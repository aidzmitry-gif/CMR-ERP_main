"""MDM — качество мастер-данных контрагентов в ядре (дедуп / merge / survivorship).

Сервисный слой shared kernel (НЕ отдельный модуль): живёт рядом с golden record в
``public``. Матчинг — детерминированный по УНП (natural key); fuzzy по имени — Postgres
``pg_trgm`` позже. **survivorship:** непустое значение выигрывает, эталон в приоритете при
конфликте. **merge обратим** (``unmerge``): дубль архивируется и ссылается на эталон, в
реестр пишется alias; расклейка возвращает дубль и убирает alias.

Транзакцию коммитит вызывающий код (роут) — здесь только изменения сессии (§ядро).
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.domain.models import (
    AuditLog,
    Contact,
    Counterparty,
    CounterpartyAlias,
    SurvivorshipRule,
)

#: порог похожести имён по умолчанию для fuzzy-кандидатов (0..1); ниже — не предлагаем.
FUZZY_THRESHOLD = 0.6

#: орг-формы и шум, мешающие сравнению имён (убираем перед похожестью).
_NAME_NOISE = re.compile(
    r"\b(ооо|оао|зао|чуп|ип|уп|одо|общество|акционерное|открытое|закрытое|частное|"
    r"unitarnoe|ltd|llc|inc|gmbh)\b",
    re.IGNORECASE,
)


def _normalize_name(name: str) -> str:
    """Привести имя к виду для сравнения: lower, без орг-форм, кавычек и лишних пробелов."""
    s = (name or "").lower().replace("«", " ").replace("»", " ").replace('"', " ")
    s = _NAME_NOISE.sub(" ", s)
    s = re.sub(r"[^\w\s]", " ", s, flags=re.UNICODE)
    return re.sub(r"\s+", " ", s).strip()

#: поля контрагента, участвующие в survivorship при слиянии
_SURVIVORSHIP_FIELDS = ("name", "unp")

#: префикс ссылки на контрагента в журнале аудита (``entity_ref``)
AUDIT_ENTITY_PREFIX = "counterparty:"


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


async def import_preview(session: AsyncSession, onec) -> dict:
    """Dry-run предпросмотр импорта контрагентов из кэша 1С в MDM — БЕЗ записи (REF3-9).

    Читает кэш 1С через фасад (``onec.fetch_counterparties`` — только чтение) и считает, сколько
    записей при реальном прогоне СОЗДАЛОСЬ БЫ / совпало по УНП с активным эталоном / без УНП
    (нельзя детерминированно сматчить). Матч — по УНП (natural key), как ``match_candidates``.
    НИЧЕГО не пишет: реальный upsert/дедуп — зона Синк (``reference_import``), здесь только метрика
    готовности моста (мост ~4109 контрагентов сейчас откачен). Возврат:
    ``{total, would_create, would_match_by_unp, without_unp}``.
    """
    cache = await onec.fetch_counterparties()
    existing_unps = {
        u
        for (u,) in (
            await session.execute(
                select(Counterparty.unp).where(
                    Counterparty.is_active.is_(True), Counterparty.unp.is_not(None)
                )
            )
        ).all()
    }
    total = would_create = would_match = without_unp = 0
    for rec in cache:
        total += 1
        unp = (rec.get("unp") or rec.get("УНП") or "").strip() if isinstance(rec, dict) else ""
        if not unp:
            without_unp += 1
        elif unp in existing_unps:
            would_match += 1
        else:
            would_create += 1
    return {
        "total": total,
        "would_create": would_create,
        "would_match_by_unp": would_match,
        "without_unp": without_unp,
    }


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


async def fuzzy_candidates(
    session: AsyncSession,
    *,
    name: str,
    exclude_id: int | None = None,
    threshold: float = FUZZY_THRESHOLD,
    limit: int = 10,
) -> list[dict]:
    """Похожие по имени активные контрагенты — кандидаты на дедуп (опечатки/регистр/орг-форма).

    Ловит дубли БЕЗ совпадения УНП (пустой/кривой УНП), которые ``match_candidates`` пропускает.
    Это **кандидаты на approval, не авто-merge** — человек-в-контуре решает (концепция §7.2).
    На Postgres — ``pg_trgm`` (``similarity``, расширение в миграции 0046); на SQLite (dev/тесты)
    — Python-фолбэк (``difflib`` над нормализованными именами). ``[{id, name, score}]`` по убыванию.

    # ponytail: (1) ``threshold`` — общий для двух разных шкал (pg_trgm similarity vs
    # SequenceMatcher.ratio), recall на SQLite и Postgres слегка расходится; калибровать порог
    # отдельно по движку, если важна точность. (2) SQLite-фолбэк сканирует все активные имена
    # в Python (O(n)) — ок на dev-объёмах; на проде работает Postgres-ветка с SQL-фильтром.
    """
    norm = _normalize_name(name)
    if not norm:
        return []
    dialect = session.bind.dialect.name if session.bind is not None else "sqlite"

    if dialect == "postgresql":
        sim = func.similarity(func.lower(Counterparty.name), name.lower())
        query = (
            select(Counterparty.id, Counterparty.name, sim.label("score"))
            .where(Counterparty.is_active.is_(True), sim >= threshold)
            .order_by(sim.desc())
            .limit(limit)
        )
        if exclude_id is not None:
            query = query.where(Counterparty.id != exclude_id)
        rows = (await session.execute(query)).all()
        return [{"id": r.id, "name": r.name, "score": float(r.score)} for r in rows]

    # SQLite-фолбэк: тянем активные имена и считаем похожесть в Python (dev-объёмы малы).
    q = select(Counterparty.id, Counterparty.name).where(Counterparty.is_active.is_(True))
    if exclude_id is not None:
        q = q.where(Counterparty.id != exclude_id)
    scored = [
        {"id": cid, "name": cname,
         "score": SequenceMatcher(None, norm, _normalize_name(cname)).ratio()}
        for cid, cname in (await session.execute(q)).all()
    ]
    scored = [s for s in scored if s["score"] >= threshold]
    scored.sort(key=lambda s: s["score"], reverse=True)
    return scored[:limit]


def _apply_survivorship(survivor: Counterparty, duplicate: Counterparty) -> None:
    """Непустое значение выигрывает; эталон в приоритете при конфликте (заполняем пустое).

    Дефолт при merge (стратегия ``non_empty_wins``). Правила-как-данные применяются на пути
    импорта (``reference_import`` + ``survivorship``); при ручном merge дублей эталон в
    приоритете — расширить до загрузки правил можно, когда появятся не-``non_empty_wins``
    поля, конфликтующие именно при слиянии (YAGNI).
    """
    for field in _SURVIVORSHIP_FIELDS:
        if not getattr(survivor, field) and getattr(duplicate, field):
            setattr(survivor, field, getattr(duplicate, field))


def _entity_ref(counterparty_id: int) -> str:
    """Ссылка на контрагента в аудите/событиях — формат ``counterparty:<id>``."""
    return f"{AUDIT_ENTITY_PREFIX}{counterparty_id}"


async def merge(
    session: AsyncSession, event_bus, survivor_id: int, duplicate_id: int, *, by: str = ""
) -> Counterparty:
    """Слить ``duplicate`` в ``survivor``: survivorship + архив дубля + alias. Обратимо.

    Пишет доменное событие ``counterparty.merged`` в outbox (та же транзакция) —
    relay проецирует его в ``AuditLog`` по ``entity_ref=counterparty:<survivor_id>``,
    наполняя историю изменений карточки эталона.
    """
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
    event_bus.emit(
        session,
        "counterparty.merged",
        {"entity_ref": _entity_ref(survivor_id), "by": by,
         "survivor_id": survivor_id, "duplicate_id": duplicate_id, "duplicate_name": duplicate.name},
    )
    return survivor


async def unmerge(
    session: AsyncSession, event_bus, duplicate_id: int, *, by: str = ""
) -> Counterparty:
    """Расклеить ранее слитый дубль: вернуть активность, снять ссылку, убрать merge-alias.

    Событие ``counterparty.unmerged`` уходит в аудит эталона, из которого расклеили.
    """
    duplicate = await session.get(Counterparty, duplicate_id)
    if duplicate is None or duplicate.merged_into_id is None:
        raise ValueError("запись не является слитым дублем")
    survivor_id = duplicate.merged_into_id
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
    event_bus.emit(
        session,
        "counterparty.unmerged",
        {"entity_ref": _entity_ref(survivor_id), "by": by,
         "survivor_id": survivor_id, "duplicate_id": duplicate_id, "duplicate_name": duplicate.name},
    )
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


async def counterparty_card(session: AsyncSession, counterparty_id: int) -> dict | None:
    """Карточка эталона контрагента: реквизиты + источники (alias) + слитые дубли + контакты + аудит.

    Витрина одной записи golden record: откуда она пришла (1С/Bitrix), какие дубли в неё
    слиты (обратимо), кто контактные лица и история изменений (проекция событий по
    ``entity_ref = counterparty:<id>``). ``None`` — записи нет.
    """
    cp = await session.get(Counterparty, counterparty_id)
    if cp is None:
        return None

    alias_rows = await aliases(session, counterparty_id)
    merged = (
        await session.execute(
            select(Counterparty)
            .where(Counterparty.merged_into_id == counterparty_id)
            .order_by(Counterparty.id)
        )
    ).scalars().all()
    contacts = (
        await session.execute(
            select(Contact)
            .where(Contact.counterparty_id == counterparty_id)
            .order_by(Contact.is_primary.desc(), Contact.id)
        )
    ).scalars().all()
    audit = (
        await session.execute(
            select(AuditLog)
            .where(AuditLog.entity_ref == f"{AUDIT_ENTITY_PREFIX}{counterparty_id}")
            .order_by(AuditLog.id.desc())
            .limit(50)
        )
    ).scalars().all()

    return {
        "id": cp.id,
        "name": cp.name,
        "unp": cp.unp,
        "is_active": cp.is_active,
        "merged_into_id": cp.merged_into_id,
        # M2: происхождение по полям {field: {source, at}} — карточка рисует бейдж источника
        "provenance": cp.provenance or {},
        "aliases": [
            {"source": a.source, "external_ref": a.external_ref, "created_at": str(a.created_at)}
            for a in alias_rows
        ],
        "merged_duplicates": [{"id": d.id, "name": d.name, "unp": d.unp} for d in merged],
        "contacts": [
            {"id": c.id, "full_name": c.full_name, "phone": c.phone,
             "email": c.email, "is_primary": c.is_primary}
            for c in contacts
        ],
        "audit": [
            {"id": a.id, "ts": str(a.ts), "actor": a.actor, "action": a.action, "detail": a.detail}
            for a in audit
        ],
    }


async def survivorship_rules(session: AsyncSession, entity_type: str | None = None) -> list[dict]:
    """Правила слияния (survivorship) — какое поле за каким источником закреплено (M2).

    Витрина таблицы ``survivorship_rule``: для каждой пары (сущность, поле) — стратегия и,
    для ``source_priority``, упорядоченный список источников. Поля без своей записи берут
    дефолт ``non_empty_wins`` (его на витрине не показываем — правил для него нет в БД).
    ``entity_type`` фильтрует (counterparty/sku); пусто — все. Только чтение.
    """
    query = select(SurvivorshipRule).order_by(
        SurvivorshipRule.entity_type, SurvivorshipRule.field
    )
    if entity_type:
        query = query.where(SurvivorshipRule.entity_type == entity_type)
    rows = (await session.execute(query)).scalars().all()
    return [
        {
            "id": r.id,
            "entity_type": r.entity_type,
            "field": r.field,
            "strategy": r.strategy,
            "source_priority": list(r.source_priority or []),
        }
        for r in rows
    ]
