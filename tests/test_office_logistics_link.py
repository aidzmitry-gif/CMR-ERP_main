"""Сквозная связка офис ↔ логистика (Блок 3) через реальные подписки шины.

Гоняем события через ``core.event_bus.relay_once`` (как фоновый relay), чтобы
проверить именно зарегистрированные в ``module.register`` подписки:
- office → logistics: ``logistics.delivery.requested`` (спот → Shipment, договор → RFQ);
- logistics → office: ``logistics.delivery.tracking`` / ``.delivered`` обновляют документ.
"""
from types import SimpleNamespace

from sqlalchemy import select

from core.runtime.app import create_app
from modules.logistics.models import CarrierRfq, Shipment
from modules.office import events as office_events
from modules.office.models import OfficeDoc


def _core_and_ctx(session):
    core = create_app().state.core
    return core, SimpleNamespace(session=session, services=core.services)


# --- office → logistics -------------------------------------------------------
async def test_spot_request_creates_shipment_via_subscription(session):
    core, ctx = _core_and_ctx(session)
    core.event_bus.emit(session, "logistics.delivery.requested", {
        "log_ref": "ЛОГ-2026-0001", "number": "ДОК-2026-0001", "company": "ООО Альфа",
        "title": "АКБ 280Ач", "weight": "420", "carrier": "cdek", "carrier_name": "СДЭК",
        "region": "Гомель", "deal_id": 7,
    })
    processed = await core.event_bus.relay_once(session, ctx)
    assert processed >= 1
    ships = (await session.execute(select(Shipment))).scalars().all()
    assert len(ships) == 1
    s = ships[0]
    assert s.number == "ЛОГ-2026-0001"          # = log_ref офиса → обратная связка по нему
    assert s.carrier == "СДЭК" and s.carrier_code == "cdek"
    assert float(s.weight_kg) == 420 and s.route_to == "Гомель" and s.status == "planned"


async def test_contract_request_creates_tender_via_subscription(session):
    core, ctx = _core_and_ctx(session)
    core.event_bus.emit(session, "logistics.delivery.requested", {
        "mode": "contract", "number": "ДОК-2026-0002", "title": "Накопитель 10кВтч",
        "weight": "900", "region": "Брест", "amount": "52000", "owner": "Ольга К.",
    })
    await core.event_bus.relay_once(session, ctx)
    rfqs = (await session.execute(select(CarrierRfq))).scalars().all()
    assert len(rfqs) == 1
    r = rfqs[0]
    assert r.number.startswith("ТНД-2026-") and r.status == "draft"
    assert r.office_doc_ref == "ДОК-2026-0002" and float(r.weight_kg) == 900
    assert r.route_to == "Брест" and r.created_by == "Ольга К."
    # отгрузка при договорном маршруте не создаётся (сначала тендер)
    assert (await session.execute(select(Shipment))).scalars().all() == []


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


async def test_office_request_handler_ctx_none_is_noop():
    from modules.logistics.events import on_office_delivery_requested
    await on_office_delivery_requested({"log_ref": "X"}, None)  # ctx=None → ранний выход


async def test_non_numeric_weight_falls_back_to_zero(session):
    from modules.logistics.events import _to_decimal, on_office_delivery_requested
    assert float(_to_decimal("не число")) == 0       # парсинг мусора → 0
    ctx = SimpleNamespace(session=session, services=SimpleNamespace(
        event_bus=__import__("core.services.eventbus", fromlist=["OutboxEventBus"]).OutboxEventBus()))
    await on_office_delivery_requested(
        {"log_ref": "ЛОГ-2026-0009", "company": "X", "weight": "тяжёлый"}, ctx)
    ship = (await session.execute(select(Shipment))).scalars().one()
    assert float(ship.weight_kg) == 0
