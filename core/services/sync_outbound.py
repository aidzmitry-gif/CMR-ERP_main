"""Исходящая выгрузка мастер-данных ERP → внешняя система (1С) — M3.

ERP — система-истина: запись, рождённая в ERP, ставится в очередь (``sync_link`` с
``state=pending, direction=out``) и доезжает во внешнюю систему через шлюз
``core.services.onec.post_document``. Идемпотентно: повтор по ``(entity_type, entity_id,
system)`` обновляет существующий линк, а не плодит. Конфликты ERP↔1С разрешает survivorship
(M2) на входящем пути — здесь только исходящий.

Чистый сервис ядра: транзакцию коммитит вызывающий (роут/фоновый relay). Реальный OData-POST
живёт в ``OneCClient.post_document`` (модуль integrations) за gateway-протоколом — этот сервис
от его реализации не зависит (mock или живая 1С — контракт один).
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.domain.models import SyncLink

#: сколько pending-линков обрабатывать за один проход relay (защита от длинного тика).
FLUSH_BATCH = 50


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def enqueue(
    session: AsyncSession,
    *,
    entity_type: str,
    entity_id: int,
    origin: str = "erp",
    system: str = "1c",
) -> SyncLink:
    """Поставить запись в очередь на выгрузку (или вернуть существующий линк, переоткрыв его).

    Идемпотентно по ``(entity_type, entity_id, system)``. Уже выгруженная запись (``synced``)
    переводится в ``pending`` повторно (правка требует переотправки); линк без внешнего id —
    остаётся pending. Записи, пришедшие ИЗ внешней системы (``origin != "erp"``), в очередь на
    выгрузку не ставятся — их источник истины снаружи.
    """
    link = (
        await session.execute(
            select(SyncLink).where(
                SyncLink.entity_type == entity_type,
                SyncLink.entity_id == entity_id,
                SyncLink.system == system,
            )
        )
    ).scalars().first()
    if link is None:
        link = SyncLink(
            entity_type=entity_type, entity_id=entity_id, system=system,
            origin=origin, direction="out", state="pending",
        )
        session.add(link)
        return link
    # существующий линк: повторная правка ERP-записи → снова в очередь
    if link.origin == "erp":
        link.state = "pending"
        link.error_text = None
    return link


def _payload_for(entity_type: str, entity) -> dict:
    """Сформировать payload документа 1С из ORM-записи. Расширяется при добавлении сущностей."""
    if entity_type == "counterparty":
        return {"number": entity.unp or "", "name": entity.name, "unp": entity.unp}
    if entity_type == "sku":
        return {"number": entity.code, "name": entity.title, "unit": entity.unit}
    raise ValueError(f"неизвестный entity_type для выгрузки: {entity_type}")


async def _load_entity(session: AsyncSession, entity_type: str, entity_id: int):
    # импорт здесь, чтобы избежать цикла models↔service на уровне модуля
    from core.domain.models import Counterparty, Sku

    model = {"counterparty": Counterparty, "sku": Sku}.get(entity_type)
    if model is None:
        return None
    return await session.get(model, entity_id)


async def flush_pending(session: AsyncSession, gateway, *, limit: int = FLUSH_BATCH) -> dict:
    """Выгрузить pending-линки во внешнюю систему через ``gateway.post_document``.

    Вызывается фоновым relay (или роутом «выгрузить сейчас»). Успех → ``external_ref`` из ответа,
    ``state=synced``; ошибка/отсутствие записи → ``state=error`` с текстом (виден в журнале,
    ручной повтор). Возвращает сводку для журнала/лога.
    """
    if gateway is None:
        return {"sent": 0, "errors": 0, "skipped": 0, "reason": "gateway недоступен"}

    pending = (
        await session.execute(
            select(SyncLink)
            .where(SyncLink.state == "pending", SyncLink.direction == "out")
            .order_by(SyncLink.id)
            .limit(limit)
        )
    ).scalars().all()

    sent = errors = 0
    for link in pending:
        # весь шаг по одному линку под try: сбой одного (отказ 1С, нет записи, кривой payload)
        # помечает только его error и НЕ роняет тик — иначе исключение откатило бы уже
        # выгруженные в этом проходе линки при общем commit фонового цикла.
        try:
            entity = await _load_entity(session, link.entity_type, link.entity_id)
            if entity is None:
                raise ValueError("запись не найдена")
            result = await gateway.post_document(link.entity_type, _payload_for(link.entity_type, entity))
            link.external_ref = result.get("ref")
            link.state = "synced"
            link.error_text = None
            link.last_synced_at = _utcnow()
            sent += 1
        except Exception as exc:  # noqa: BLE001 — фиксируем в state=error, тик продолжается
            link.state = "error"
            link.error_text = str(exc)[:255]
            errors += 1

    return {"sent": sent, "errors": errors, "skipped": 0}


async def journal(session: AsyncSession, *, limit: int = 100) -> list[dict]:
    """Журнал выгрузки — последние линки (что/куда/статус/когда/ошибка)."""
    rows = (
        await session.execute(select(SyncLink).order_by(SyncLink.id.desc()).limit(limit))
    ).scalars().all()
    return [
        {
            "id": r.id, "entity_type": r.entity_type, "entity_id": r.entity_id,
            "system": r.system, "origin": r.origin, "direction": r.direction,
            "state": r.state, "external_ref": r.external_ref,
            "last_synced_at": str(r.last_synced_at) if r.last_synced_at else None,
            "error_text": r.error_text,
        }
        for r in rows
    ]
