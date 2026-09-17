from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from modules.office import events
from modules.office.models import OfficeDoc


class Result:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def scalars(self):
        return self

    def first(self):
        return self.rows[0] if self.rows else None


class Session:
    def __init__(self, *results):
        self.results = list(results)
        self.added = []
        self.flushes = 0

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        self.flushes += 1
        for value in self.added:
            if getattr(value, "id", None) is None:
                value.id = 17

    async def execute(self, _statement):
        return self.results.pop(0) if self.results else Result()


class Bus:
    def __init__(self):
        self.events = []

    def emit(self, session, event_type, payload):
        self.events.append((event_type, payload))


def ctx(session, bus):
    return SimpleNamespace(session=session, services=SimpleNamespace(event_bus=bus))


def doc(**changes):
    values = dict(
        id=3,
        number="ДОК-3",
        company="Альфа",
        title="АКБ",
        amount=Decimal("100"),
        stage="await_pay",
        docs_status="",
        owner="",
        region="Минск",
        weight="",
        address="",
        sales_ref="СД-3",
        wms_ref="",
        logistics_ref="",
        finance_ref="",
        overdue_days=9,
        delivery="",
        op_date="",
    )
    values.update(changes)
    return SimpleNamespace(**values)


@pytest.mark.asyncio
async def test_deal_won_creates_document_and_three_outbox_commands():
    session = Session(Result())
    bus = Bus()

    await events.on_deal_won(
        {"deal_id": 42, "deal_ref": "СД-42", "company": "Альфа", "product": "АКБ", "amount": 200},
        ctx(session, bus),
    )

    created = session.added[0]
    assert isinstance(created, OfficeDoc)
    assert (created.id, created.number, created.deal_id, created.stage) == (17, "ДОК-2026-0017", 42, "ready")
    assert [event[0] for event in bus.events] == [
        "office.doc.created",
        "office.reservation.requested",
        "office.shipment.requested",
    ]


@pytest.mark.asyncio
async def test_deal_won_is_idempotent_when_existing_document_is_found():
    existing = doc()
    session = Session(Result([existing]))
    bus = Bus()

    await events.on_deal_won({"deal_ref": "СД-3"}, ctx(session, bus))

    assert session.added == [] and bus.events == []


@pytest.mark.asyncio
async def test_inbound_handlers_update_shipment_delivery_payment_and_tracking():
    shipment = doc()
    await events.on_shipment_completed({"sales_ref": "СД-3", "wms_ref": "WMS-9"}, ctx(Session(Result([shipment])), Bus()))
    assert (shipment.stage, shipment.wms_ref, shipment.docs_status) == ("shipped", "WMS-9", "Отгружено, готовим документы")

    delivery = doc()
    await events.on_delivery_delivered(
        {"number": "ДОК-3", "carrier": "СДЭК", "date": "2026-09-20"},
        ctx(Session(Result([delivery])), Bus()),
    )
    assert (delivery.delivery, delivery.op_date, delivery.docs_status) == (
        "СДЭК", "2026-09-20", "Доставлено, закрываем документы"
    )

    partial = doc()
    await events.on_payment_received(
        {"deal_id": 42, "ref": "СЧ-42", "outstanding": "20"},
        ctx(Session(Result([partial])), Bus()),
    )
    assert partial.stage == "await_pay" and "20 BYN" in partial.docs_status

    paid = doc(overdue_days=12)
    await events.on_payment_received(
        {"deal_id": 42, "ref": "СЧ-42", "outstanding": "0"},
        ctx(Session(Result([paid])), Bus()),
    )
    assert (paid.stage, paid.finance_ref, paid.overdue_days, paid.next_step) == (
        "paid", "СЧ-42", 0, "Сделка закрыта"
    )

    tracked = doc()
    await events.on_delivery_tracking(
        {"logistics_ref": "ЛОГ-3", "tracking_status": "В пути", "carrier_name": "DPD"},
        ctx(Session(Result([tracked])), Bus()),
    )
    assert (tracked.docs_status, tracked.delivery) == ("Доставка: В пути", "DPD")


@pytest.mark.asyncio
async def test_inbound_handlers_ignore_unknown_documents_without_side_effects():
    context = ctx(Session(Result()), Bus())
    await events.on_shipment_completed({"wms_ref": "missing"}, context)
    await events.on_delivery_delivered({"log_ref": "missing"}, context)
    await events.on_payment_received({"deal_id": 999}, context)
    await events.on_delivery_tracking({"log_ref": "missing"}, context)
    assert context.session.added == []
