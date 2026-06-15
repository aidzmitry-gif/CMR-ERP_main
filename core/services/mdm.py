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

from core.domain.models import AuditLog, Contact, Counterparty, CounterpartyAlias

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
