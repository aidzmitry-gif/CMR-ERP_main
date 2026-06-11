"""API- и обработчик-тесты модуля office: связи отделов, заявка перевозчику, эскалация.

Эмиссию проверяем через outbox: роуты/обработчики пишут ``OutboxEvent`` в ту же
сессию (фикстура ``session`` = та же, что подменяет ``get_session`` у ``api``),
поэтому после вызова читаем события прямо из таблицы. Фоновый relay в тестах не
крутится (ASGITransport без lifespan), события остаются необработанными — то, что нужно.
"""
from types import SimpleNamespace

from sqlalchemy import select

from core.domain.models import OutboxEvent
from core.services.eventbus import OutboxEventBus
from modules.office import events
from modules.office.models import OfficeDoc


async def _event_types(session) -> list[str]:
    rows = (await session.execute(select(OutboxEvent).order_by(OutboxEvent.id))).scalars().all()
    return [r.event_type for r in rows]


def _ctx(session):
    """Контекст доставки события обработчику: сессия + фасад сервисов с шиной."""
    return SimpleNamespace(session=session, services=SimpleNamespace(event_bus=OutboxEventBus()))


# --------------------------------------------------------------------------- #
#  Роуты: CRUD, доска, справочник перевозчиков
# --------------------------------------------------------------------------- #
async def test_create_doc_emits_created_and_autonumbers(api, session):
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


async def test_board_groups_by_stage(api):
    await api.post("/office/docs", json={"company": "ООО Бета", "amount": 100})
    board = (await api.get("/office/board")).json()
    assert [s["id"] for s in board["stages"]] == ["ready", "shipped", "docs", "await_pay", "paid"]
    assert board["stages"][0]["count"] >= 1


# --------------------------------------------------------------------------- #
#  Роут смены стадии → события отделам + лестница эскалации
# --------------------------------------------------------------------------- #
async def test_update_stage_emits_department_events(api, session):
    doc_id = (await api.post("/office/docs", json={"company": "ООО Гамма", "amount": 200})).json()["id"]

    await api.patch(f"/office/docs/{doc_id}", json={"stage": "ready"})    # → Склад
    await api.patch(f"/office/docs/{doc_id}", json={"stage": "docs"})     # → Финансы
    types = await _event_types(session)
    assert "office.shipment.requested" in types
    assert "office.docs.collected" in types


async def test_update_stage_await_pay_triggers_awaiting_and_ladder(api, session):
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


async def test_update_stage_unknown_and_missing(api):
    doc_id = (await api.post("/office/docs", json={"company": "X", "amount": 1})).json()["id"]
    assert (await api.patch(f"/office/docs/{doc_id}", json={"stage": "bogus"})).status_code == 422
    assert (await api.patch("/office/docs/999999", json={"stage": "paid"})).status_code == 404


# --------------------------------------------------------------------------- #
#  Заявка перевозчику: happy-path + гард стадии + ошибки
# --------------------------------------------------------------------------- #
async def test_carrier_request_happy_path(api, session):
    doc_id = (await api.post("/office/docs", json={"company": "ООО Эпсилон", "amount": 9000})).json()["id"]
    r = await api.post(
        f"/office/docs/{doc_id}/carrier-request",
        json={"carrier": "cdek", "region": "Гомель", "pickup_date": "2026-06-15", "contact": "Склад"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["log_ref"].startswith("ЛОГ-2026-")
    assert body["carrier"] == "СДЭК"
    assert body["region"] == "Гомель"
    assert body["doc"]["logistics_ref"] == body["log_ref"]
    assert "logistics.delivery.requested" in await _event_types(session)


async def test_carrier_request_guard_non_ready_stage(api):
    doc_id = (await api.post("/office/docs", json={"company": "ООО Дзета", "amount": 100})).json()["id"]
    await api.patch(f"/office/docs/{doc_id}", json={"stage": "shipped"})  # уже отгружено
    r = await api.post(f"/office/docs/{doc_id}/carrier-request", json={"carrier": "cdek"})
    assert r.status_code == 409  # нельзя заказывать доставку не со стадии «Готово к отгрузке»


async def test_carrier_request_unknown_carrier_and_missing_doc(api):
    doc_id = (await api.post("/office/docs", json={"company": "ООО Эта", "amount": 100})).json()["id"]
    assert (await api.post(f"/office/docs/{doc_id}/carrier-request", json={"carrier": "nope"})).status_code == 422
    assert (await api.post("/office/docs/999999/carrier-request", json={"carrier": "cdek"})).status_code == 404


# --------------------------------------------------------------------------- #
#  Входящие обработчики событий отделов
# --------------------------------------------------------------------------- #
async def test_on_deal_won_creates_doc_and_dedupes(session):
    ctx = _ctx(session)
    payload = {"deal_ref": "D-100", "company": "ООО Альфа", "title": "АКБ 60Ач",
               "amount": 15000, "owner": "Иванов", "region": "Минск"}
    await events.on_deal_won(payload, ctx)

    docs = (await session.execute(select(OfficeDoc))).scalars().all()
    assert len(docs) == 1
    doc = docs[0]
    assert doc.stage == "ready" and doc.sales_ref == "D-100"
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


async def test_on_payment_received_clears_overdue(session):
    session.add(OfficeDoc(number="ДОК-2026-0052", finance_ref="СЧ-9", stage="await_pay", overdue_days=33))
    await session.flush()
    await events.on_payment_received({"finance_ref": "СЧ-9"}, _ctx(session))
    doc = (await session.execute(select(OfficeDoc).where(OfficeDoc.finance_ref == "СЧ-9"))).scalars().one()
    assert doc.stage == "paid" and doc.overdue_days == 0


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
