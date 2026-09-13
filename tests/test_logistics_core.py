# ruff: noqa: F811 -- pytest fixtures imported for this module
"""API-тесты базовой логистики (доставка РБ/РФ, импорт, перевозчики, дашборд).

Покрывают эндпоинты, существовавшие до Блока 1 (карточки воронок, заказ
перевозчику, трекинг, импортная цепочка, реестр перевозчиков, дашборд/расходы),
включая событийные ветки (delivered → закрытие сделки, таможня → склад).
"""

from types import SimpleNamespace

import pytest
from sqlalchemy import select

from core.domain.models import OutboxEvent
from modules.logistics import events
from tests.test_logistics_fixtures import exact, shipping_api  # noqa: F401


async def _event_types(session):
    rows = (await session.execute(select(OutboxEvent).order_by(OutboxEvent.id))).scalars().all()
    return [r.event_type for r in rows]


# --- Доставка РБ/РФ -----------------------------------------------------------
async def test_shipment_board_card_fields(shipping_api):
    await shipping_api.post("/logistics/shipments", json={
        "customer": "ООО Альфа", "route_from": "Минск", "route_to": "Гомель",
        "cargo": "АКБ", "weight_kg": 64, "amount": 78.4, "carrier": "Автолайт",
        "carrier_order_no": "AL-1", "tracking_no": "TRK1", "tracking_status": "В пути",
    })
    board = (await shipping_api.get("/logistics/board")).json()
    assert [s["id"] for s in board["stages"]][0] == "planned"
    card = board["stages"][0]["cards"][0]
    assert card["title"] == "ООО Альфа" and card["subtitle"] == "Минск → Гомель"
    assert "64 кг" in card["tags"] and "АКБ" in card["tags"]


async def test_carrier_order_and_delivered_event(shipping_api, session):
    sid = (await shipping_api.post("/logistics/shipments", json={"customer": "ООО Бета", "deal_id": 7})).json()["id"]
    # заказ перевозчику по коду из каталога → имя подтягивается, статус assigned
    order = await shipping_api.post(f"/logistics/shipments/{sid}/carrier-order", json={
        "carrier_code": "dpd", "shipping_cost": 28.0, "payer": "компания", "eta": "2026-06-14",
    })
    assert order.status_code == 200
    body = order.json()
    assert body["carrier"] == "DPD" and body["status"] == "assigned"
    assert body["carrier_order_no"].startswith("DPD-2026-")
    # трекинг
    trk = await shipping_api.patch(f"/logistics/shipments/{sid}/tracking", json={
        "tracking_status": "Выдан курьеру", "tracking_no": "DPD777", "eta": "2026-06-15",
    })
    assert trk.json()["tracking_no"] == "DPD777"
    # доставлено → событие закрытия сделки
    done = await shipping_api.patch(f"/logistics/shipments/{sid}", json={"status": "delivered"})
    assert done.json()["status"] == "delivered"
    types = await _event_types(session)
    assert "logistics.carrier_order.created" in types
    assert "logistics.shipment.delivered" in types


async def test_carrier_order_errors(shipping_api):
    assert (await shipping_api.post("/logistics/shipments/999/carrier-order", json={"carrier_code": "dpd"})).status_code == 404
    sid = (await shipping_api.post("/logistics/shipments", json={"customer": "X"})).json()["id"]
    # ни кода, ни имени → 400
    assert (await shipping_api.post(f"/logistics/shipments/{sid}/carrier-order", json={})).status_code == 400


async def test_update_shipment_missing(shipping_api):
    assert (await shipping_api.patch("/logistics/shipments/999", json={"status": "delivered"})).status_code == 404


# --- Импорт из Китая ----------------------------------------------------------
async def test_import_flow_and_customs_events(shipping_api, session):
    imp = await shipping_api.post("/logistics/imports", json={
        "supplier": "Shenzhen Co", "container_no": "CN123", "cargo": "Ячейки", "qty": 500,
        "amount": 12000, "incoterms": "FOB", "po_ref": "PO-9", "stage": "customs",
    })
    assert imp.status_code == 201 and imp.json()["number"].startswith("ИМП-2026-")
    iid = imp.json()["id"]
    board = (await shipping_api.get("/logistics/imports/board")).json()
    assert [s["id"] for s in board["stages"]][0] == "factory"
    assert len((await shipping_api.get("/logistics/imports")).json()) == 1
    # таможня → склад: два события (customs_cleared + arrived)
    moved = await shipping_api.patch(f"/logistics/imports/{iid}", json={"stage": "warehouse", "customs_status": "Очищено"})
    assert moved.json()["stage"] == "warehouse"
    types = await _event_types(session)
    assert "logistics.import.customs_cleared" in types and "logistics.import.arrived" in types


async def test_import_update_missing(shipping_api):
    assert (await shipping_api.patch("/logistics/imports/999", json={"stage": "warehouse"})).status_code == 404


# --- Перевозчики и дашборд ----------------------------------------------------
async def test_carriers_catalog_seed_create(shipping_api):
    cat = (await shipping_api.get("/logistics/carriers/catalog")).json()
    assert {c["code"] for c in cat} == {"dpd", "autolight", "cdek", "evropochta", "belpost"}
    seeded = await shipping_api.post("/logistics/carriers/seed")
    assert len(seeded.json()) == 5
    assert len((await shipping_api.post("/logistics/carriers/seed")).json()) == 5  # идемпотентно
    created = await shipping_api.post("/logistics/carriers", json={
        "name": "Свой транспорт", "code": "own", "kind": "РБ", "on_time_pct": 99, "avg_days": 1,
    })
    assert created.status_code == 201
    assert any(c["code"] == "own" for c in (await shipping_api.get("/logistics/carriers")).json())


async def test_dashboard_and_costs(shipping_api):
    first = await shipping_api.post("/logistics/shipments", json={"customer": "C1", "amount": 100})
    assert first.status_code == 201
    # Imports/audit have no verified org scope: never leak their global totals.
    for endpoint in ("dashboard", "costs"):
        response = await shipping_api.get("/logistics/" + endpoint)
        assert response.status_code == 409
        assert response.json()["detail"] == "organization_scope_incomplete"
    assert len((await shipping_api.get("/logistics/shipments")).json()) == 1


# --- Событие sales → logistics ------------------------------------------------
async def test_on_document_posted_creates_shipment(session):
    ctx = SimpleNamespace(session=session, services=SimpleNamespace(event_bus=__import__(
        "core.services.eventbus", fromlist=["OutboxEventBus"]).OutboxEventBus()))
    await events.on_document_posted({"kind": "order", "counterparty": "ООО Гамма", "deal_id": 5, "entity_ref": "deal:5"}, ctx)
    from modules.logistics.models import Shipment, ShipmentIntake
    rows = (await session.execute(select(Shipment))).scalars().all()
    assert rows == []
    pending = (await session.scalars(select(ShipmentIntake))).one()
    assert pending.state == "pending" and pending.snapshot["counterparty"] == "ООО Гамма"
    assert "logistics.intake.observed" in await _event_types(session)
    # Unrelated kind is ignored; relevant events require context.
    await events.on_document_posted({"kind": "invoice"}, ctx)
    with pytest.raises(ValueError, match="requires event context"):
        await events.on_document_posted({"kind": "order"}, None)
    assert (await session.execute(select(Shipment))).scalars().all() == []
