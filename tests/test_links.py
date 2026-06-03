"""Тесты межмодульных взаимосвязей (через событийную шину, §2.5)."""
from types import SimpleNamespace

from sqlalchemy import select

from core.domain.models import OutboxEvent
from core.services.eventbus import EventContext, OutboxEventBus


def _ctx(session):
    return EventContext(session=session, services=SimpleNamespace(event_bus=OutboxEventBus()))


async def test_invoice_creates_payment(session):
    from modules.finance.events import on_document_posted
    from modules.finance.models import Payment

    await on_document_posted(
        {"kind": "invoice", "number": "СЧ-1", "amount": 5000, "deal_id": 1, "entity_ref": "deal:1"},
        _ctx(session),
    )
    await session.commit()
    payments = (await session.execute(select(Payment))).scalars().all()
    assert len(payments) == 1
    assert float(payments[0].amount) == 5000 and payments[0].status == "pending"

    # не-счёт игнорируется
    await on_document_posted({"kind": "contract", "number": "ДГ-1"}, _ctx(session))
    await session.commit()
    assert len((await session.execute(select(Payment))).scalars().all()) == 1


async def test_order_creates_shipment(session):
    from modules.logistics.events import on_document_posted
    from modules.logistics.models import Shipment

    await on_document_posted(
        {"kind": "order", "counterparty": "ООО Альфа", "deal_id": 7, "entity_ref": "deal:7"},
        _ctx(session),
    )
    await session.commit()
    rows = (await session.execute(select(Shipment))).scalars().all()
    assert len(rows) == 1
    assert rows[0].customer == "ООО Альфа" and rows[0].status == "planned"


async def test_reserve_creates_stock_movement(session):
    from modules.wms.events import on_stock_reserved
    from modules.wms.models import StockMovement

    await on_stock_reserved(
        {"items": [{"sku_code": "ROLL-5", "qty": 12, "warehouse": "Склад-2"}]},
        _ctx(session),
    )
    await session.commit()
    rows = (await session.execute(select(StockMovement))).scalars().all()
    assert len(rows) == 1
    assert rows[0].sku_code == "ROLL-5" and rows[0].kind == "out" and float(rows[0].qty) == 12


async def test_goods_received_creates_stock_movement(session):
    from modules.wms.events import on_goods_received
    from modules.wms.models import StockMovement

    await on_goods_received({"item": "Болты M8", "qty": 500, "warehouse": "Главный"}, _ctx(session))
    await session.commit()
    rows = (await session.execute(select(StockMovement))).scalars().all()
    assert len(rows) == 1
    assert rows[0].sku_code == "Болты M8" and rows[0].kind == "in"


async def test_procurement_received_emits(session, api):
    req = (
        await api.post("/procurement/requests", json={"supplier": "S", "item": "Болт", "qty": 10})
    ).json()
    r = await api.patch(f"/procurement/requests/{req['id']}", json={"status": "received"})
    assert r.status_code == 200 and r.json()["status"] == "received"
    types = [e.event_type for e in (await session.execute(select(OutboxEvent))).scalars().all()]
    assert "procurement.received" in types


async def test_production_completed_emits(session, api):
    order = (await api.post("/production/orders", json={"product": "Рама", "qty": 3})).json()
    r = await api.patch(f"/production/orders/{order['id']}", json={"status": "done"})
    assert r.status_code == 200 and r.json()["status"] == "done"
    types = [e.event_type for e in (await session.execute(select(OutboxEvent))).scalars().all()]
    assert "production.completed" in types
