"""API- и обработчик-тесты модуля office: связи отделов, заявка перевозчику, эскалация.

Эмиссию проверяем через outbox: роуты/обработчики пишут ``OutboxEvent`` в ту же
сессию (фикстура ``session`` = та же, что подменяет ``get_session`` у ``api``),
поэтому после вызова читаем события прямо из таблицы. Фоновый relay в тестах не
крутится (ASGITransport без lifespan), события остаются необработанными — то, что нужно.
"""
from types import SimpleNamespace

import pytest_asyncio
from sqlalchemy import select

from core.domain.models import OutboxEvent, User
from core.services.eventbus import OutboxEventBus
from core.services.shipping_payload import canonical_shipping_payload
from modules.office import events
from modules.office.models import OfficeDoc
from modules.office.shipping_producer import source_hash
from tests.test_shipping_payload import payload as shipping_payload


@pytest_asyncio.fixture
async def office_actor(api):
    api.headers["X-User"] = "office-test"
    return api


async def _event_types(session) -> list[str]:
    rows = (await session.execute(select(OutboxEvent).order_by(OutboxEvent.id))).scalars().all()
    return [r.event_type for r in rows]


def _ctx(session):
    """Контекст доставки события обработчику: сессия + фасад сервисов с шиной."""
    return SimpleNamespace(session=session, services=SimpleNamespace(event_bus=OutboxEventBus()))


# --------------------------------------------------------------------------- #
#  Роуты: CRUD, доска, справочник перевозчиков
# --------------------------------------------------------------------------- #
async def test_create_doc_emits_created_and_autonumbers(office_actor, session):
    api = office_actor
    r = await api.post("/office/docs", json={"company": "ООО Альфа", "title": "АКБ", "amount": 850000})
    assert r.status_code == 201
    assert r.json()["number"].startswith("ДОК-2026-")
    assert "office.doc.created" in await _event_types(session)


async def test_carriers_catalog(api):
    carriers = (await api.get("/office/carriers")).json()
    ids = {c["id"] for c in carriers}
    assert ids == {"cdek", "evropochta", "belpochta", "dellin", "dpd", "own"}
    own = next(c for c in carriers if c["id"] == "own")
    assert own["name"] == "Свой транспорт" and own["heavy"] is True


async def test_board_groups_by_stage(office_actor):
    api = office_actor
    await api.post("/office/docs", json={"company": "ООО Бета", "amount": 100})
    board = (await api.get("/office/board")).json()
    assert [s["id"] for s in board["stages"]] == ["ready", "shipped", "docs", "await_pay", "paid"]
    assert board["stages"][0]["count"] >= 1


# --------------------------------------------------------------------------- #
#  Роут смены стадии → события отделам + лестница эскалации
# --------------------------------------------------------------------------- #
async def test_update_stage_emits_department_events(office_actor, session):
    api = office_actor
    doc_id = (await api.post("/office/docs", json={"company": "ООО Гамма", "amount": 200})).json()["id"]

    await api.patch(f"/office/docs/{doc_id}", json={"stage": "ready"})    # → Склад
    await api.patch(f"/office/docs/{doc_id}", json={"stage": "docs"})     # → Финансы
    types = await _event_types(session)
    assert "office.shipment.requested" in types
    assert "office.docs.collected" in types


async def test_update_stage_await_pay_triggers_awaiting_and_ladder(office_actor, session):
    api = office_actor
    doc_id = (await api.post("/office/docs", json={"company": "ООО Дельта", "amount": 50000})).json()["id"]
    # выставляем просрочку напрямую в строке — лестница смотрит overdue_days
    doc = await session.get(OfficeDoc, doc_id)
    doc.overdue_days = 20  # > 15 → ступень «претензия» (Юрист)
    await session.flush()

    await api.patch(f"/office/docs/{doc_id}", json={"stage": "await_pay"})
    types = await _event_types(session)
    assert "office.payment.awaiting" in types
    assert "office.claim.requested" in types  # ступень лестницы по 20 дням

    awaiting = next(
        r for r in (await session.execute(select(OutboxEvent))).scalars().all()
        if r.event_type == "office.payment.awaiting"
    )
    assert awaiting.payload["large_receivable"] is True  # 50000 > 10000


async def test_update_stage_unknown_and_missing(office_actor):
    api = office_actor
    doc_id = (await api.post("/office/docs", json={"company": "X", "amount": 1})).json()["id"]
    assert (await api.patch(f"/office/docs/{doc_id}", json={"stage": "bogus"})).status_code == 422
    assert (await api.patch("/office/docs/999999", json={"stage": "paid"})).status_code == 404


# --------------------------------------------------------------------------- #
#  Заявка перевозчику: happy-path + гард стадии + ошибки
# --------------------------------------------------------------------------- #
@pytest_asyncio.fixture
async def shipping_doc(office_actor, session):
    session.add(User(username="office-test", full_name="Reviewer", role="director", status="active"))
    await session.commit()
    r = await office_actor.post("/office/docs", json={"company": "ООО Эпсилон", "amount": 9000})
    assert r.status_code == 201
    doc = await session.get(OfficeDoc, r.json()["id"])
    assignment = await office_actor.post(f"/office/docs/{doc.id}/shipping-reviewer", json={
        "subject": "office-test", "expected_revision": 0, "evidence": "Проверка первичного документа",
    })
    assert assignment.status_code == 200
    return doc


def carrier_request_body(doc):
    return {"request_key": "office-request-1", "expected_source_hash": source_hash(doc),
            "expected_assignment_revision": 1, "intent": shipping_payload()["intent"]}


async def test_carrier_request_happy_path(office_actor, shipping_doc, session):
    url = f"/office/docs/{shipping_doc.id}/carrier-request"
    request = carrier_request_body(shipping_doc)
    r = await office_actor.post(url, json=request)
    assert r.status_code == 200
    body = r.json()
    assert body["source_sha256"] == request["expected_source_hash"]
    assert body["payload"]["intent"] == request["intent"]
    assert canonical_shipping_payload(body["payload"])[1] == body["payload_sha256"]
    assert body["payload"]["source_refs"]["document_id"] == shipping_doc.id
    replay = await office_actor.post(url, json=request)
    assert replay.status_code == 200 and replay.json() == body
    assert (await _event_types(session)).count("logistics.delivery.requested") == 1
    # Preparation alone must not claim an executed delivery.
    await session.refresh(shipping_doc)
    assert not shipping_doc.logistics_ref
    assert shipping_doc.stage == "ready"


async def test_carrier_request_guard_non_ready_stage(office_actor, shipping_doc, session):
    r = await office_actor.patch(f"/office/docs/{shipping_doc.id}", json={"stage": "shipped"})
    assert r.status_code == 200
    await session.refresh(shipping_doc)
    r = await office_actor.post(f"/office/docs/{shipping_doc.id}/carrier-request",
                               json=carrier_request_body(shipping_doc))
    assert r.status_code == 409
    assert "logistics.delivery.requested" not in await _event_types(session)


async def test_carrier_request_rejects_legacy_payload_and_missing_doc(office_actor, shipping_doc, session):
    assert (await office_actor.post(f"/office/docs/{shipping_doc.id}/carrier-request",
                                   json={"carrier": "cdek"})).status_code == 422
    assert (await office_actor.post("/office/docs/999999/carrier-request",
                                   json=carrier_request_body(shipping_doc))).status_code == 404
    assert "logistics.delivery.requested" not in await _event_types(session)


# --------------------------------------------------------------------------- #
#  Входящие обработчики событий отделов
# --------------------------------------------------------------------------- #
async def test_on_deal_won_creates_doc_and_dedupes(session):
    ctx = _ctx(session)
    # payload — как реально эмитит sales/routes.py sales.deal.won (deal_id + number)
    payload = {"deal_id": 100, "number": "СД-2026-0100", "company": "ООО Альфа", "title": "АКБ 60Ач",
               "amount": 15000, "owner": "Иванов", "region": "Минск"}
    await events.on_deal_won(payload, ctx)

    docs = (await session.execute(select(OfficeDoc))).scalars().all()
    assert len(docs) == 1
    doc = docs[0]
    assert doc.stage == "ready" and doc.sales_ref == "СД-2026-0100"
    assert doc.deal_id == 100  # целочисленная ручка сохранена — join с финансами по оплате
    assert doc.number.startswith("ДОК-2026-")
    types = await _event_types(session)
    assert {"office.doc.created", "office.reservation.requested", "office.shipment.requested"} <= set(types)

    # повторная доставка того же события → второй документ не заводится (дедуп по sales_ref)
    await events.on_deal_won(payload, ctx)
    assert len((await session.execute(select(OfficeDoc))).scalars().all()) == 1


async def test_on_shipment_completed_moves_to_shipped(session):
    session.add(OfficeDoc(number="ДОК-2026-0050", sales_ref="D-50", stage="ready"))
    await session.flush()
    await events.on_shipment_completed({"sales_ref": "D-50", "wms_ref": "W-7"}, _ctx(session))
    doc = (await session.execute(select(OfficeDoc).where(OfficeDoc.sales_ref == "D-50"))).scalars().one()
    assert doc.stage == "shipped" and doc.wms_ref == "W-7"


async def test_on_delivery_delivered_updates_tracking(session):
    session.add(OfficeDoc(number="ДОК-2026-0051", logistics_ref="ЛОГ-2026-0051", stage="shipped"))
    await session.flush()
    await events.on_delivery_delivered(
        {"log_ref": "ЛОГ-2026-0051", "carrier_name": "СДЭК", "delivered_at": "2026-06-12"}, _ctx(session)
    )
    doc = (await session.execute(select(OfficeDoc).where(OfficeDoc.logistics_ref == "ЛОГ-2026-0051"))).scalars().one()
    assert doc.delivery == "СДЭК" and doc.op_date == "2026-06-12"


async def test_on_payment_received_full_closes_by_deal_id(session):
    """Реальный контракт finance.payment.received: сопоставление по deal_id, остаток 0 → «Оплачено».

    Раньше тест слал синтетический ``{finance_ref}`` — ключ, которого в событии финансов нет,
    поэтому шов был мёртв в проде, а тест зелен. Теперь — как эмитит finance/routes.py.
    """
    session.add(OfficeDoc(number="ДОК-2026-0052", deal_id=52, stage="await_pay", overdue_days=33))
    await session.flush()
    await events.on_payment_received(
        {"ref": "СЧ-9", "amount": "15000", "entity_ref": "payment:7",
         "deal_id": 52, "counterparty_ref": None, "outstanding": "0"},
        _ctx(session),
    )
    doc = (await session.execute(select(OfficeDoc).where(OfficeDoc.deal_id == 52))).scalars().one()
    assert doc.stage == "paid" and doc.overdue_days == 0
    assert doc.finance_ref == "СЧ-9"  # номер счёта 1С сохранён как провенанс связи


async def test_on_payment_received_partial_keeps_open(session):
    """Частичная оплата (outstanding>0) НЕ закрывает документ — не врём про деньги (PLATFORM #1)."""
    session.add(OfficeDoc(number="ДОК-2026-0053", deal_id=53, stage="await_pay", overdue_days=10))
    await session.flush()
    await events.on_payment_received(
        {"ref": "СЧ-10", "amount": "5000", "entity_ref": "payment:8",
         "deal_id": 53, "outstanding": "10000"},
        _ctx(session),
    )
    doc = (await session.execute(select(OfficeDoc).where(OfficeDoc.deal_id == 53))).scalars().one()
    assert doc.stage == "await_pay"    # ещё не оплачено полностью — стадию не двигаем
    assert doc.overdue_days == 10      # и просрочку не снимаем
    assert "10000" in doc.docs_status  # остаток виден офис-менеджеру


async def test_handlers_noop_when_doc_not_found(session):
    ctx = _ctx(session)
    # документов нет — обработчики не падают и ничего не создают
    await events.on_shipment_completed({"sales_ref": "ZZZ"}, ctx)
    await events.on_delivery_delivered({"log_ref": "ZZZ"}, ctx)
    await events.on_payment_received({"finance_ref": "ZZZ"}, ctx)
    assert (await session.execute(select(OfficeDoc))).scalars().all() == []


async def test_find_doc_skips_empty_and_unknown_fields(session):
    session.add(OfficeDoc(number="ДОК-2026-0060", sales_ref="D-60"))
    await session.flush()
    # пустое значение и несуществующее поле пропускаются, валидное — находит
    found = await events._find_doc(session, bogus="x", wms_ref="", sales_ref="D-60")
    assert found is not None and found.sales_ref == "D-60"
    assert await events._find_doc(session, sales_ref="нет-такого") is None
