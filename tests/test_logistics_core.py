"""API-тесты базовой логистики (доставка РБ/РФ, импорт, перевозчики, дашборд).

Покрывают эндпоинты, существовавшие до Блока 1 (карточки воронок, заказ
перевозчику, трекинг, импортная цепочка, реестр перевозчиков, дашборд/расходы),
включая событийные ветки (delivered → закрытие сделки, таможня → склад).
"""
from types import SimpleNamespace

from sqlalchemy import select

from core.domain.models import OutboxEvent
from modules.logistics import events


async def _event_types(session):
    rows = (await session.execute(select(OutboxEvent).order_by(OutboxEvent.id))).scalars().all()
    return [r.event_type for r in rows]


# --- Доставка РБ/РФ -----------------------------------------------------------
async def test_shipment_board_card_fields(api):
    await api.post("/logistics/shipments", json={
        "customer": "ООО Альфа", "route_from": "Минск", "route_to": "Гомель",
        "cargo": "АКБ", "weight_kg": 64, "amount": 78.4, "carrier": "Автолайт",
        "carrier_order_no": "AL-1", "tracking_no": "TRK1", "tracking_status": "В пути",
    })
    board = (await api.get("/logistics/board")).json()
    assert [s["id"] for s in board["stages"]][0] == "planned"
    card = board["stages"][0]["cards"][0]
    assert card["title"] == "ООО Альфа" and card["subtitle"] == "Минск → Гомель"
    assert "64 кг" in card["tags"] and "АКБ" in card["tags"]


async def test_carrier_order_and_delivered_event(api, session):
    sid = (await api.post("/logistics/shipments", json={"customer": "ООО Бета", "deal_id": 7})).json()["id"]
    # заказ перевозчику по коду из каталога → имя подтягивается, статус assigned
    order = await api.post(f"/logistics/shipments/{sid}/carrier-order", json={
        "carrier_code": "dpd", "shipping_cost": 28.0, "payer": "компания", "eta": "2026-06-14",
    })
    assert order.status_code == 200
    body = order.json()
    assert body["carrier"] == "DPD" and body["status"] == "assigned"
    assert body["carrier_order_no"].startswith("DPD-2026-")
    # трекинг
    trk = await api.patch(f"/logistics/shipments/{sid}/tracking", json={
        "tracking_status": "Выдан курьеру", "tracking_no": "DPD777", "eta": "2026-06-15",
    })
    assert trk.json()["tracking_no"] == "DPD777"
    # доставлено → событие закрытия сделки
    done = await api.patch(f"/logistics/shipments/{sid}", json={"status": "delivered"})
    assert done.json()["status"] == "delivered"
    types = await _event_types(session)
    assert "logistics.carrier_order.created" in types
    assert "logistics.shipment.delivered" in types


async def test_carrier_order_errors(api):
    assert (await api.post("/logistics/shipments/999/carrier-order", json={"carrier_code": "dpd"})).status_code == 404
    sid = (await api.post("/logistics/shipments", json={"customer": "X"})).json()["id"]
    # ни кода, ни имени → 400
    assert (await api.post(f"/logistics/shipments/{sid}/carrier-order", json={})).status_code == 400


async def test_update_shipment_missing(api):
    assert (await api.patch("/logistics/shipments/999", json={"status": "delivered"})).status_code == 404


# --- Импорт из Китая ----------------------------------------------------------
async def test_import_flow_and_customs_events(api, session):
    imp = await api.post("/logistics/imports", json={
        "supplier": "Shenzhen Co", "container_no": "CN123", "cargo": "Ячейки", "qty": 500,
        "amount": 12000, "incoterms": "FOB", "po_ref": "PO-9", "stage": "customs",
    })
    assert imp.status_code == 201 and imp.json()["number"].startswith("ИМП-2026-")
    iid = imp.json()["id"]
    board = (await api.get("/logistics/imports/board")).json()
    assert [s["id"] for s in board["stages"]][0] == "factory"
    assert len((await api.get("/logistics/imports")).json()) == 1
    # таможня → склад: два события (customs_cleared + arrived)
    moved = await api.patch(f"/logistics/imports/{iid}", json={"stage": "warehouse", "customs_status": "Очищено"})
    assert moved.json()["stage"] == "warehouse"
    types = await _event_types(session)
    assert "logistics.import.customs_cleared" in types and "logistics.import.arrived" in types


async def test_import_update_missing(api):
    assert (await api.patch("/logistics/imports/999", json={"stage": "warehouse"})).status_code == 404


# --- Перевозчики и дашборд ----------------------------------------------------
async def test_carriers_catalog_seed_create(api):
    cat = (await api.get("/logistics/carriers/catalog")).json()
    assert {c["code"] for c in cat} == {"dpd", "autolight", "cdek", "evropochta", "belpost"}
    seeded = await api.post("/logistics/carriers/seed")
    assert len(seeded.json()) == 5
    assert len((await api.post("/logistics/carriers/seed")).json()) == 5  # идемпотентно
    created = await api.post("/logistics/carriers", json={
        "name": "Свой транспорт", "code": "own", "kind": "РБ", "on_time_pct": 99, "avg_days": 1,
    })
    assert created.status_code == 201
    assert any(c["code"] == "own" for c in (await api.get("/logistics/carriers")).json())


async def test_dashboard_and_costs(api):
    await api.post("/logistics/carriers", json={"name": "DPD", "code": "dpd", "on_time_pct": 96, "avg_days": 2})
    await api.post("/logistics/shipments", json={"customer": "C1", "carrier": "DPD", "amount": 100, "status": "in_transit", "payer": "компания"})
    await api.post("/logistics/shipments", json={"customer": "C2", "carrier": "DPD", "amount": 50, "status": "delivered", "payer": "клиент"})
    dash = (await api.get("/logistics/dashboard")).json()
    assert dash["delivery_in_transit"] == 1 and dash["delivered_total"] == 1
    assert dash["avg_delivery_days"] == 2.0 and dash["on_time_pct"] == 96.0
    assert dash["cost_by_carrier"][0]["carrier"] == "DPD"
    costs = (await api.get("/logistics/costs")).json()
    assert costs["company"] == 100.0 and costs["client"] == 50.0 and costs["total"] == 150.0


# --- Событие sales → logistics ------------------------------------------------
async def test_on_document_posted_creates_shipment(session):
    ctx = SimpleNamespace(session=session, services=SimpleNamespace(event_bus=__import__(
        "core.services.eventbus", fromlist=["OutboxEventBus"]).OutboxEventBus()))
    await events.on_document_posted({"kind": "order", "counterparty": "ООО Гамма", "deal_id": 5, "entity_ref": "deal:5"}, ctx)
    from modules.logistics.models import Shipment
    rows = (await session.execute(select(Shipment))).scalars().all()
    assert len(rows) == 1 and rows[0].customer == "ООО Гамма" and rows[0].status == "planned"
    assert "logistics.shipment.created" in await _event_types(session)
    # не заказ / нет ctx → ничего
    await events.on_document_posted({"kind": "invoice"}, ctx)
    await events.on_document_posted({"kind": "order"}, None)
    assert len((await session.execute(select(Shipment))).scalars().all()) == 1
