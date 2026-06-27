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
    r = await api.patch(f"/procurement/requests/{req['id']}", json={"stage": "qc"})
    assert r.status_code == 200 and r.json()["stage"] == "qc"
    types = [e.event_type for e in (await session.execute(select(OutboxEvent))).scalars().all()]
    assert "procurement.received" in types


async def test_production_completed_emits(session, api):
    order = (await api.post("/production/orders", json={"product": "Рама", "qty": 3})).json()
    r = await api.patch(f"/production/orders/{order['id']}", json={"stage": "done"})
    assert r.status_code == 200 and r.json()["stage"] == "done"
    types = [e.event_type for e in (await session.execute(select(OutboxEvent))).scalars().all()]
    assert "production.completed" in types


# --- обратные связи, замыкающие циклы ---


async def test_campaign_creates_leads(session):
    from modules.sales.events import on_campaign_launched
    from modules.sales.models import Lead

    # кампания питает приём лидов (front-of-funnel), а не создаёт сделки напрямую
    await on_campaign_launched({"name": "Весна", "leads": 3, "channel": "email"}, _ctx(session))
    await session.commit()
    leads = (await session.execute(select(Lead).where(Lead.status == "new"))).scalars().all()
    assert len(leads) == 3
    assert all(lead.source == "email" for lead in leads)


async def test_payment_paid_marks_document(session):
    from modules.sales.events import on_payment_paid
    from modules.sales.models import Deal, DealDocument

    deal = Deal(number="PD-1", title="t", counterparty="c")
    session.add(deal)
    await session.flush()
    doc = DealDocument(deal_id=deal.id, kind="invoice", number="СЧ-PD-1", status="posted")
    session.add(doc)
    await session.commit()

    await on_payment_paid({"ref": "СЧ-PD-1"}, _ctx(session))
    await session.commit()
    await session.refresh(doc)
    assert doc.status == "paid"


async def test_shipment_delivered_wins_deal(session):
    from modules.sales.events import on_shipment_delivered
    from modules.sales.models import Deal

    deal = Deal(number="SD-1", title="t", counterparty="c", stage="prop")
    session.add(deal)
    await session.flush()
    await on_shipment_delivered({"deal_id": deal.id}, _ctx(session))
    await session.commit()
    await session.refresh(deal)
    assert deal.stage == "won"


async def test_marketing_launch_emits(session, api):
    camp = (
        await api.post(
            "/marketing/campaigns",
            json={"name": "К", "channel": "email", "budget": 100, "leads": 5},
        )
    ).json()
    r = await api.post(f"/marketing/campaigns/{camp['id']}/launch")
    assert r.status_code == 200
    types = [e.event_type for e in (await session.execute(select(OutboxEvent))).scalars().all()]
    assert "marketing.campaign.launched" in types


async def test_finance_paid_emits(session, api):
    pay = (await api.post("/finance/payments", json={"ref": "СЧ-X", "amount": 100})).json()
    r = await api.patch(f"/finance/payments/{pay['id']}", json={"status": "paid"})
    assert r.status_code == 200
    types = [e.event_type for e in (await session.execute(select(OutboxEvent))).scalars().all()]
    assert "finance.payment.paid" in types


async def test_logistics_delivered_emits(session, api):
    ship = (await api.post("/logistics/shipments", json={"customer": "K"})).json()
    r = await api.patch(f"/logistics/shipments/{ship['id']}", json={"status": "delivered"})
    assert r.status_code == 200
    types = [e.event_type for e in (await session.execute(select(OutboxEvent))).scalars().all()]
    assert "logistics.shipment.delivered" in types


async def test_freight_cost_creates_finance_expense(session):
    from modules.finance.events import on_freight_cost
    from modules.finance.models import Payment

    await on_freight_cost(
        {"deal_id": 7, "ref": "ОТГ-1", "carrier": "DPD", "amount": 320.50}, _ctx(session)
    )
    await session.commit()
    rows = (await session.execute(select(Payment).where(Payment.kind == "freight"))).scalars().all()
    assert len(rows) == 1
    assert float(rows[0].amount) == 320.50 and rows[0].ref == "freight:ОТГ-1"

    # нулевой тариф не создаёт расход
    await on_freight_cost({"ref": "ОТГ-2", "amount": 0}, _ctx(session))
    await session.commit()
    assert len((await session.execute(select(Payment).where(Payment.kind == "freight"))).scalars().all()) == 1


async def test_freight_refund_creates_credit(session):
    from modules.finance.events import on_freight_refund
    from modules.finance.models import Payment

    # переплата перевозчику (variance>0) → кредит против фрахта: kind=freight_refund, сумма < 0
    await on_freight_refund(
        {"shipment_code": "ЛОГ-1", "carrier": "dpd", "amount": 50, "entity_ref": "audit:3"},
        _ctx(session),
    )
    await session.commit()
    rows = (
        await session.execute(select(Payment).where(Payment.kind == "freight_refund"))
    ).scalars().all()
    assert len(rows) == 1
    assert float(rows[0].amount) == -50.0 and rows[0].ref == "freight_refund:audit:3"

    # нулевая/пустая сумма не создаёт записи
    await on_freight_refund({"shipment_code": "ЛОГ-2", "amount": 0}, _ctx(session))
    await session.commit()
    assert len(
        (await session.execute(select(Payment).where(Payment.kind == "freight_refund"))).scalars().all()
    ) == 1


async def test_delivered_shipment_emits_freight_cost(session, api):
    ship = (await api.post("/logistics/shipments", json={"customer": "K"})).json()
    # назначаем перевозчика с тарифом → amount > 0
    await api.post(
        f"/logistics/shipments/{ship['id']}/carrier-order",
        json={"carrier": "DPD", "shipping_cost": 150},
    )
    await api.patch(f"/logistics/shipments/{ship['id']}", json={"status": "delivered"})
    types = [e.event_type for e in (await session.execute(select(OutboxEvent))).scalars().all()]
    assert "logistics.freight.cost" in types


async def test_freight_audit_overbill_emits_refund(session, api):
    # счёт перевозчика больше тарифа → переплата → событие «к возврату»
    r = await api.post(
        "/logistics/costs/audit",
        json={"shipment_code": "ЛОГ-1", "carrier_code": "dpd",
              "invoice_amount": 250, "expected_amount": 200},
    )
    assert r.status_code == 201 and float(r.json()["variance"]) == 50
    types = [e.event_type for e in (await session.execute(select(OutboxEvent))).scalars().all()]
    assert "logistics.freight.audit_refund" in types

    # счёт ≤ тарифа → переплаты нет → события нет
    await api.post(
        "/logistics/costs/audit",
        json={"shipment_code": "ЛОГ-2", "carrier_code": "dpd",
              "invoice_amount": 180, "expected_amount": 200},
    )
    refunds = [e for e in (await session.execute(select(OutboxEvent))).scalars().all()
               if e.event_type == "logistics.freight.audit_refund"]
    assert len(refunds) == 1
