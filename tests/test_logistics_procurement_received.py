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
