"""Сквозная связка офис ↔ логистика (Блок 3) через реальные подписки шины.

Гоняем события через ``core.event_bus.relay_once`` (как фоновый relay), чтобы
проверить именно зарегистрированные в ``module.register`` подписки:
- office → logistics: ``logistics.delivery.requested`` (спот → Shipment, договор → RFQ);
- logistics → office: ``logistics.delivery.tracking`` / ``.delivered`` обновляют документ.
"""
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from core.runtime.app import create_app
from core.services.eventbus import EventContext
from modules.logistics.models import CarrierRfq, Shipment, ShipmentIntake
from modules.office import events as office_events
from modules.office.models import OfficeDoc

# Producer integration fixtures; this section uses actual dispatcher/adapters,
# organization/source facades, consumer, execution and per-event relay sessions.
from tests.test_logistics_invoice_binding import exact  # noqa: F401
from tests.test_office_shipping_associations import office, prepare_office  # noqa: F401
from tests.test_sales_shipping_associations import confirmation, order, prepare_order  # noqa: F401
from tests.test_shipping_payload import payload as canonical_payload


@pytest.mark.parametrize("mode", ["spot", "contract"])
async def test_real_both_producers_http_outbox_relay_one_target(api, session, office, order, exact, mode):  # noqa: F811
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from core.services.logistics import ShippingProducerDispatcher
    from modules.logistics.models import ShippingExecution
    from modules.office.shipping_producer import OfficeShippingProducer
    from modules.sales.shipping_producer import SalesShippingProducer

    core = create_app().state.core
    core.services.shipping_producer = ShippingProducerDispatcher(
        order=SalesShippingProducer(core), office=OfficeShippingProducer(core))
    intent = {**canonical_payload()["intent"], "mode": mode}
    first = await prepare_order(api, order, intent)
    second, _ = await prepare_office(api, office, intent)
    for url, data in [
        ("/sales/deals/1/documents/10/shipping-association-confirm", confirmation(first, exact)),
        (f"/office/docs/{office.id}/shipping-association-confirm", confirmation(second, exact, assignment=1)),
    ]:
        response = await api.post(url, json=data)
        assert response.status_code == 200, response.text
    factory = async_sessionmaker(session.bind, expire_on_commit=False)
    filters = ["sales.document.posted", "logistics.delivery.requested"]
    assert await core.event_bus.relay_pending(factory, core.services, event_types=filters) == 2
    assert await core.event_bus.relay_pending(factory, core.services, event_types=filters) == 0
    await session.rollback()
    intakes = list(await session.scalars(select(ShipmentIntake)))
    assert len(intakes) == 2 and all(r.state == "resolved" for r in intakes)
    assert len(list(await session.scalars(select(ShippingExecution)))) == 1
    targets = list(await session.scalars(select(CarrierRfq if mode == "contract" else Shipment)))
    assert len(targets) == 1
    assert len({r.rfq_id if mode == "contract" else r.shipment_id for r in intakes}) == 1


async def test_office_real_late_bind_manual_resolve_terminal_replay(api, session, office, exact):  # noqa: F811
    from sqlalchemy import update
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from core.domain.models import OutboxEvent
    from core.services.logistics import ShippingProducerDispatcher
    from modules.office.shipping_producer import OfficeShippingProducer
    from modules.sales.models import DealDocument
    from modules.sales.shipping_producer import SalesShippingProducer

    core = api._transport.app.state.core
    core.services.shipping_producer = ShippingProducerDispatcher(
        order=SalesShippingProducer(core), office=OfficeShippingProducer(core))
    envelope, _ = await prepare_office(api, office)
    doc_id = office.id
    factory = async_sessionmaker(session.bind, expire_on_commit=False)
    assert await core.event_bus.relay_pending(factory, core.services, event_types=["logistics.delivery.requested"]) == 1
    await session.rollback()
    intake = (await session.scalars(select(ShipmentIntake))).one()
    intake_id = intake.id
    assert intake.state == "pending" and intake.request_digest == envelope["payload_sha256"]
    result = await api.post(f"/office/docs/{doc_id}/shipping-association-confirm", json=confirmation(envelope, exact, assignment=1))
    assert result.status_code == 200, result.text
    result = await api.post(f"/logistics/intakes/{intake_id}/resolve")
    assert result.status_code == 200 and result.json()["state"] == "resolved", result.text
    shipment_id = result.json()["shipment_id"]
    await session.execute(update(DealDocument).where(DealDocument.id == 1).values(status="cancelled"))
    await session.commit()
    before = len(list(await session.scalars(select(OutboxEvent))))
    result = await api.post(f"/logistics/intakes/{intake_id}/resolve")
    assert result.status_code == 200 and result.json()["shipment_id"] == shipment_id, result.text
    assert len(list(await session.scalars(select(OutboxEvent)))) == before
    changed = {**envelope["payload"], "intent": {**envelope["payload"]["intent"], "cargo": "Forged"},
               "payload_sha256": envelope["payload_sha256"]}
    await session.execute(update(ShipmentIntake).where(ShipmentIntake.id == intake_id).values(snapshot=changed))
    await session.commit()
    result = await api.post(f"/logistics/intakes/{intake_id}/resolve")
    assert result.status_code == 409, result.text


def _core_and_ctx(session):
    core = create_app().state.core
    return core, EventContext(session=session, services=core.services)


# --- office → logistics -------------------------------------------------------
async def test_spot_request_creates_shipment_via_subscription(session):
    core, ctx = _core_and_ctx(session)
    payload = {"mode": "spot", "log_ref": "LOG1", "company": "Synthetic", "weight": "64"}
    core.event_bus.emit(session, "logistics.delivery.requested", payload)
    await core.event_bus.relay_once(session, ctx)
    assert list(await session.scalars(select(Shipment))) == []
    intake = (await session.scalars(select(ShipmentIntake))).one()
    assert intake.state == "pending" and intake.snapshot == payload


async def test_contract_request_creates_tender_via_subscription(session):
    core, ctx = _core_and_ctx(session)
    payload = {"mode": "contract", "log_ref": "LOG2", "company": "Synthetic", "weight": "900"}
    core.event_bus.emit(session, "logistics.delivery.requested", payload)
    await core.event_bus.relay_once(session, ctx)
    assert list(await session.scalars(select(Shipment))) == []
    assert list(await session.scalars(select(CarrierRfq))) == []
    intake = (await session.scalars(select(ShipmentIntake))).one()
    assert intake.state == "pending" and intake.snapshot["mode"] == "contract"


# --- logistics → office -------------------------------------------------------
async def test_tracking_event_updates_office_doc(session):
    core, ctx = _core_and_ctx(session)
    session.add(OfficeDoc(number="ДОК-2026-0003", logistics_ref="ЛОГ-2026-0003", stage="shipped"))
    await session.flush()
    core.event_bus.emit(session, "logistics.delivery.tracking", {
        "log_ref": "ЛОГ-2026-0003", "tracking_status": "В пути · Минск → Гомель", "carrier_name": "СДЭК",
    })
    await core.event_bus.relay_once(session, ctx)
    doc = (await session.execute(select(OfficeDoc).where(OfficeDoc.logistics_ref == "ЛОГ-2026-0003"))).scalars().one()
    assert doc.docs_status == "Доставка: В пути · Минск → Гомель" and doc.delivery == "СДЭК"


async def test_delivered_event_closes_office_doc(session):
    core, ctx = _core_and_ctx(session)
    session.add(OfficeDoc(number="ДОК-2026-0004", logistics_ref="ЛОГ-2026-0004", stage="shipped"))
    await session.flush()
    core.event_bus.emit(session, "logistics.delivery.delivered", {
        "log_ref": "ЛОГ-2026-0004", "carrier_name": "СДЭК", "delivered_at": "2026-06-15",
    })
    await core.event_bus.relay_once(session, ctx)
    doc = (await session.execute(select(OfficeDoc).where(OfficeDoc.logistics_ref == "ЛОГ-2026-0004"))).scalars().one()
    assert doc.docs_status == "Доставлено, закрываем документы" and doc.op_date == "2026-06-15"


async def test_tracking_handler_noop_when_doc_missing(session):
    ctx = SimpleNamespace(session=session, services=None)
    await office_events.on_delivery_tracking({"log_ref": "НЕТ-ТАКОГО", "tracking_status": "В пути"}, ctx)
    assert (await session.execute(select(OfficeDoc))).scalars().all() == []


async def test_office_request_handler_ctx_none_fails():
    from modules.logistics.events import on_office_delivery_requested
    with pytest.raises(ValueError, match="requires event context"):
        await on_office_delivery_requested({"log_ref": "X"}, None)


async def test_non_numeric_weight_falls_back_to_zero(session):
    from modules.logistics.events import _to_decimal, on_office_delivery_requested
    assert float(_to_decimal("не число")) == 0       # парсинг мусора → 0
    ctx = SimpleNamespace(session=session, services=SimpleNamespace(
        event_bus=__import__("core.services.eventbus", fromlist=["OutboxEventBus"]).OutboxEventBus()))
    await on_office_delivery_requested(
        {"log_ref": "ЛОГ-2026-0009", "company": "X", "weight": "тяжёлый"}, ctx)
    assert list(await session.scalars(select(Shipment))) == []
    intake = (await session.scalars(select(ShipmentIntake))).one()
    assert intake.snapshot["weight"] == "тяжёлый" and intake.state == "pending"
