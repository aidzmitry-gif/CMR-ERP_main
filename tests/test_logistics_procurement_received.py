"""Подписка logistics на procurement.received (LOG3-3 phantom-guard + LOG3-4 расширенный payload).

Логистика лишь ОТРАЖАЕТ факт приёмки закупки. Контракт круга 3:
- если ImportShipment по po_ref уже есть — обновляем stage=warehouse + эмитим info-эвент;
- если записи нет и payload не несёт import-маркера → ничего не создаём (LOG3-3);
- если import-маркер есть — заводим запись;
- payload import.received несёт freight_amount(str), eta, supplier (LOG3-4).
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

import pytest
from sqlalchemy import select

from modules.logistics.events import _looks_like_import, on_procurement_received
from modules.logistics.models import ImportShipment


class _SeenBus:
    """Тестовый event-bus, копит эмиты (тип, payload, флаг ack) и не пишет в БД."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def emit(self, _session, event_type: str, payload: dict) -> None:
        self.events.append((event_type, payload))


class _Ctx:
    def __init__(self, session, bus):
        self.session = session
        self.services = type("S", (), {"event_bus": bus})()


@pytest.mark.unit
def test_looks_like_import_origin():
    """Явный маркер origin='import' → True."""
    assert _looks_like_import({"origin": "import"})
    assert _looks_like_import({"origin": "IMPORT"})
    assert not _looks_like_import({"origin": "domestic"})
    assert not _looks_like_import({})


@pytest.mark.unit
def test_looks_like_import_incoterms_or_country():
    """Непустой incoterms или явно не-внутренняя страна → True.

    «Внутренний рынок» CRM — РБ + РФ. Импорт ≠ просто «не РБ» (M1 ревью круга 3).
    """
    assert _looks_like_import({"incoterms": "FOB"})
    assert _looks_like_import({"incoterms": "CIF"})
    assert _looks_like_import({"country": "CN"})
    assert _looks_like_import({"country": "Китай"})
    # «Внутренние» страны — НЕ импорт
    assert not _looks_like_import({"country": "РБ"})
    assert not _looks_like_import({"country": "BY"})
    assert not _looks_like_import({"country": "РФ"})       # M1: РФ — внутренний рынок CRM
    assert not _looks_like_import({"country": "RU"})
    assert not _looks_like_import({"country": "Россия"})
    assert not _looks_like_import({"country": ""})
    assert not _looks_like_import({"incoterms": "  "})  # пробелы не считаются


# --- Круг 5 харднинг: таблица классификации стран/маркеров ----------------
# Фиксируем КАЖДЫЙ пограничный случай явно — тест-харднинг по докладу координатора
# (round5: «пограничные страны таблицей»). Любое изменение списка _DOMESTIC_COUNTRIES
# или эвристики origin/incoterms должно либо проходить эту таблицу, либо обновлять её.

@pytest.mark.unit
@pytest.mark.parametrize(
    "payload, expected, why",
    [
        # --- внутренние страны (НЕ импорт) ---
        ({"country": "РБ"}, False, "канон Беларусь"),
        ({"country": "BY"}, False, "ISO2 BY"),
        ({"country": "BLR"}, False, "ISO3 BLR"),
        ({"country": "Беларусь"}, False, "полное имя кириллицей"),
        ({"country": "Belarus"}, False, "полное имя латиницей"),
        ({"country": "РФ"}, False, "M1 ревью: РФ — внутренний рынок CRM"),
        ({"country": "RU"}, False, "ISO2 RU"),
        ({"country": "RUS"}, False, "ISO3 RUS"),
        ({"country": "Россия"}, False, "полное имя кириллицей"),
        ({"country": "Russia"}, False, "полное имя латиницей"),
        ({"country": " РБ "}, False, "пробелы вокруг — strip должен сработать"),
        ({"country": "by"}, False, "регистр игнорируется (upper)"),
        # --- внешние страны (импорт по стране) ---
        ({"country": "CN"}, True, "Китай ISO2"),
        ({"country": "Китай"}, True, "Китай кириллицей"),
        ({"country": "UA"}, True, "Украина ISO2"),
        ({"country": "Украина"}, True, "Украина кириллицей"),
        ({"country": "PL"}, True, "Польша ISO2"),
        ({"country": "Польша"}, True, "Польша кириллицей"),
        ({"country": "DE"}, True, "Германия — внешний рынок"),
        ({"country": "TR"}, True, "Турция — внешний рынок"),
        # --- origin маркер (приоритет) ---
        ({"origin": "import"}, True, "явный маркер origin"),
        ({"origin": "IMPORT"}, True, "регистр в origin"),
        ({"origin": "domestic"}, False, "явный domestic — не импорт (нет других маркеров)"),
        # --- incoterms маркер ---
        ({"incoterms": "FOB"}, True, "FOB — экспортный термин"),
        ({"incoterms": "CIF"}, True, "CIF — экспортный термин"),
        ({"incoterms": "EXW"}, True, "EXW — Incoterms 2020"),
        ({"incoterms": "DAP"}, True, "DAP"),
        ({"incoterms": ""}, False, "пустой incoterms — нет маркера"),
        ({"incoterms": "  "}, False, "только пробелы — нет маркера"),
        # --- пустой / нерелевантный payload ---
        ({}, False, "пустой payload — нет маркеров"),
        ({"item": "Винт", "qty": 100}, False, "только груз — нет маркеров импорта"),
        ({"country": None, "incoterms": None}, False, "None-поля не падают"),
        ({"country": ""}, False, "пустая страна = неопределённо"),
        # --- комбинированные ---
        ({"country": "CN", "incoterms": "FOB"}, True, "оба маркера — импорт"),
        ({"country": "РБ", "incoterms": "FOB"}, True, "incoterms сильнее: incoterms у локальной поставки = аномалия → импорт"),
        ({"country": "CN", "origin": "domestic"}, True, "страна перевешивает: CN явно импорт"),
    ],
)
def test_looks_like_import_table(payload, expected, why):
    """Параметризованная таблица классификации payload procurement.received.

    DoD круга 5: фиксирует ТЕКУЩУЮ эвристику и блокирует регрессии.
    """
    assert _looks_like_import(payload) is expected, (
        f"payload={payload!r} ожидался {'импорт' if expected else 'НЕ импорт'} ({why})"
    )


@pytest.mark.api
async def test_internal_purchase_no_marker_no_record(api, session):
    """LOG3-3: внутренняя закупка без import-маркера и без существующей записи → запись НЕ создаётся."""
    bus = _SeenBus()
    ctx = _Ctx(session, bus)
    await on_procurement_received(
        {"entity_ref": "purchase:42", "item": "Винт М6", "qty": 100, "supplier": "ООО Винт"},
        ctx,
    )
    await session.flush()
    rows = (await session.execute(select(ImportShipment))).scalars().all()
    assert rows == [], "внутренняя закупка не должна создавать ImportShipment"
    # info-эвент тоже НЕ должен полететь (нечего описывать)
    assert not any(t == "logistics.import.received" for t, _ in bus.events)


@pytest.mark.api
async def test_import_marker_creates_record_with_extended_payload(api, session):
    """LOG3-3+LOG3-4: с маркером импорта запись заводится и info-эвент несёт freight_amount/eta/supplier."""
    bus = _SeenBus()
    ctx = _Ctx(session, bus)
    await on_procurement_received(
        {
            "entity_ref": "purchase:101",
            "item": "Чехлы 100шт",
            "qty": 100,
            "supplier": "Shenzhen Co.",
            "origin": "import",
            "incoterms": "FOB",
        },
        ctx,
    )
    await session.flush()
    rows = (await session.execute(select(ImportShipment))).scalars().all()
    assert len(rows) == 1
    obj = rows[0]
    assert obj.po_ref == "purchase:101"
    assert obj.stage == "warehouse"
    assert obj.supplier == "Shenzhen Co."

    sent = [p for t, p in bus.events if t == "logistics.import.received"]
    assert len(sent) == 1
    payload = sent[0]
    # LOG3-4: расширенный payload
    assert payload["po_ref"] == "purchase:101"
    assert isinstance(payload["freight_amount"], str), "LOG3-4: деньги — str, не float"
    # Сравниваем по значению (str(Decimal('0')) и str(Decimal('0.00')) — разные литералы).
    try:
        assert Decimal(payload["freight_amount"]) == Decimal(obj.amount)
    except InvalidOperation:
        pytest.fail(f"freight_amount нечисловой: {payload['freight_amount']!r}")
    assert payload["supplier"] == "Shenzhen Co."
    assert "eta" in payload
    assert payload["entity_ref"] == obj.number


@pytest.mark.api
async def test_update_existing_record_without_marker(api, session):
    """LOG3-3: если запись по po_ref уже есть — обновляем stage=warehouse даже без маркера.

    Запись уже считалась импортом (её завели раньше), поэтому стадия двигается; эвент летит.
    """
    # Заводим запись «руками» — имитируем ранее существовавший импорт
    obj = ImportShipment(
        po_ref="purchase:202", cargo="Старый груз", qty=50, supplier="Поставщик",
        stage="customs", amount=Decimal("1500.00"),
    )
    session.add(obj)
    await session.flush()
    if not obj.number:
        obj.number = f"ИМП-2026-{obj.id:04d}"

    bus = _SeenBus()
    ctx = _Ctx(session, bus)
    await on_procurement_received(
        {"entity_ref": "purchase:202", "item": "Доп.строка", "qty": 50},  # без маркера
        ctx,
    )
    await session.flush()
    await session.refresh(obj)
    assert obj.stage == "warehouse"
    sent = [p for t, p in bus.events if t == "logistics.import.received"]
    assert len(sent) == 1
    assert isinstance(sent[0]["freight_amount"], str)
    assert Decimal(sent[0]["freight_amount"]) == Decimal("1500.00")


@pytest.mark.api
async def test_idempotency_repeat_does_not_change_stage(api, session):
    """Повтор procurement.received не «откатывает» stage и эмитит каждый раз (info-сигнал).

    Эмит идемпотентен по содержанию — нет дублирования финансовых движений (LOG3-1
    проверяет идемпотентность через update_import, тут лишь info-приёмка повторяется).
    """
    obj = ImportShipment(
        po_ref="purchase:303", cargo="Запчасть", qty=10, supplier="X",
        stage="warehouse", amount=Decimal("0"),
    )
    session.add(obj)
    await session.flush()
    if not obj.number:
        obj.number = f"ИМП-2026-{obj.id:04d}"

    bus = _SeenBus()
    ctx = _Ctx(session, bus)
    payload_in = {"entity_ref": "purchase:303", "item": "Запчасть", "qty": 10}
    await on_procurement_received(payload_in, ctx)
    await on_procurement_received(payload_in, ctx)
    await session.flush()
    await session.refresh(obj)
    assert obj.stage == "warehouse"
    # Эвент INFO; два раза — норма, нет финансовой проводки.
    assert sum(1 for t, _ in bus.events if t == "logistics.import.received") == 2


@pytest.mark.api
async def test_empty_entity_ref_noop(api, session):
    """Пустой entity_ref → молча выходим (контракт: po_ref обязателен)."""
    bus = _SeenBus()
    ctx = _Ctx(session, bus)
    await on_procurement_received({"item": "X"}, ctx)
    await on_procurement_received({"entity_ref": "order:42", "item": "X"}, ctx)  # не purchase:*
    await session.flush()
    assert (await session.execute(select(ImportShipment))).scalars().all() == []
    assert bus.events == []


# --- Круг 5 харднинг: import.received без подписчиков не роняет шину --------

@pytest.mark.api
async def test_import_received_no_subscribers_does_not_break_bus(session):
    """R5-4: INFO-эвент `logistics.import.received` эмитится и доставляется БЕЗ подписчиков.

    Контракт LOG3-4: «оставлено INFO без обязательного подписчика — осознанно». Тест
    проверяет, что relay при отсутствии handlers НЕ кидает исключение, OutboxEvent
    помечается processed_at и пишется AuditLog-проекция (как для любого события).
    """
    from core.domain.models import AuditLog, OutboxEvent
    from core.services.eventbus import EventContext, OutboxEventBus

    bus = OutboxEventBus()
    # Никаких subscribe(...) — потребителей нет вообще.
    assert bus._handlers.get("logistics.import.received") is None

    bus.emit(
        session,
        "logistics.import.received",
        {
            "import_id": 1, "number": "ИМП-2026-0001",
            "po_ref": "purchase:1", "freight_amount": "1000",
            "eta": None, "supplier": "X", "entity_ref": "ИМП-2026-0001",
        },
    )
    await session.flush()

    ctx = EventContext(session=session, services=object())
    # relay_once без подписчиков — НЕ должен кинуть.
    processed = await bus.relay_once(session, ctx)
    assert processed == 1

    # Эвент помечен и аудит-проекция записана (контракт outbox-доставки).
    events = (await session.execute(select(OutboxEvent))).scalars().all()
    assert len(events) == 1 and events[0].processed_at is not None
    audits = (await session.execute(select(AuditLog))).scalars().all()
    audit = next(a for a in audits if a.action == "logistics.import.received")
    assert audit.entity_ref == "ИМП-2026-0001"


@pytest.mark.api
async def test_freight_cost_no_subscribers_does_not_break_bus(session):
    """R5-4 hardening: даже денежный freight.cost без подписчиков relay не роняет.

    Зеркальный тест: при отвалившемся finance-подписчике эмит логистики не должен
    мешать другим событиям в той же сессии (at-least-once + idempotent processed_at).
    """
    from core.domain.models import OutboxEvent
    from core.services.eventbus import EventContext, OutboxEventBus

    bus = OutboxEventBus()
    bus.emit(session, "logistics.freight.cost", {
        "ref": "import:1", "leg": "import", "amount": "8500.50",
        "po_ref": "purchase:1", "entity_ref": "import:1",
    })
    await session.flush()
    processed = await bus.relay_once(session, EventContext(session=session, services=object()))
    assert processed == 1
    e = (await session.execute(select(OutboxEvent))).scalars().first()
    assert e is not None and e.processed_at is not None
