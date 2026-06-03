"""Добор покрытия backend: guard-ветки обработчиков, резерв склада, sync 1С, загрузчик."""
import types
from types import SimpleNamespace

import pytest


def _ctx(session):
    return SimpleNamespace(session=session, services=SimpleNamespace())


def test_loader_resolve_errors(monkeypatch):
    from core.runtime import loader

    fake = types.ModuleType("modules.fake.module")
    monkeypatch.setattr(loader.importlib, "import_module", lambda name: fake)
    # нет фабрики get_module() → RuntimeError
    with pytest.raises(RuntimeError):
        loader._resolve_module("fake")
    # get_module() вернул не ModuleContract → TypeError
    fake.get_module = lambda: object()
    with pytest.raises(TypeError):
        loader._resolve_module("fake")


async def test_payment_paid_guard_branches(session):
    from modules.sales.events import on_payment_paid

    # нет ref → ранний выход; ref без документа → ничего не меняем
    await on_payment_paid({}, _ctx(session))
    await on_payment_paid({"ref": "НЕТ-ТАКОГО"}, _ctx(session))


async def test_shipment_delivered_guard_branches(session):
    from modules.sales.events import on_shipment_delivered

    # нет deal_id → ранний выход; несуществующая сделка → no-op
    await on_shipment_delivered({}, _ctx(session))
    await on_shipment_delivered({"deal_id": 999999}, _ctx(session))


async def test_stock_reserve_skip_branches(session):
    from modules.integrations.models import StockItem
    from modules.integrations.stock import StockService

    svc = StockService()
    # пустой список / без кода / нулевое qty / неизвестный SKU — всё пропускается
    assert await svc.reserve(session, []) == []
    assert await svc.reserve(session, [{"sku_code": "", "qty": 1}]) == []
    assert await svc.reserve(session, [{"sku_code": "X", "qty": 0}]) == []
    assert await svc.reserve(session, [{"sku_code": "НЕТ", "qty": 5}]) == []

    session.add(StockItem(sku_code="RS-1", warehouse="Главный", qty_available=100, qty_reserved=2))
    await session.commit()
    res = await svc.reserve(session, [{"sku_code": "RS-1", "qty": 3}])
    assert res and res[0]["sku_code"] == "RS-1" and res[0]["qty"] == 3


async def test_sync_1c_idempotent_update(api):
    # первый sync создаёт записи, второй — обновляет существующие (ветка upsert)
    r1 = await api.post("/integrations/1c/sync")
    assert r1.status_code in (200, 201)
    r2 = await api.post("/integrations/1c/sync")
    assert r2.status_code in (200, 201)


async def test_request_approval_missing_deal(api):
    r = await api.post("/sales/deals/999999/request-approval", json={"kind": "deal.contract"})
    assert r.status_code == 404


async def test_chats_dedup_same_deal(api):
    deal = (
        await api.post("/sales/deals", json={"number": "CH-D", "title": "t", "counterparty": "c"})
    ).json()
    await api.post(f"/sales/deals/{deal['id']}/messages", json={"channel": "whatsapp", "text": "первое"})
    await api.post(f"/sales/deals/{deal['id']}/messages", json={"channel": "telegram", "text": "второе"})
    chats = (await api.get("/sales/chats")).json()
    # сделка с 2 сообщениями встречается в списке чатов один раз (вторая итерация → seen)
    assert len([c for c in chats if c["deal_id"] == deal["id"]]) == 1


async def test_set_primary_contact_without_counterparty(session, api):
    from core.domain.models import Contact

    c = Contact(full_name="Контакт без контрагента", is_primary=False)  # counterparty_id=None
    session.add(c)
    await session.commit()
    r = await api.patch(f"/sales/contacts/{c.id}/primary")
    assert r.status_code == 200 and r.json()["is_primary"] is True


async def test_order_document_on_deal_without_items(api):
    deal = (
        await api.post("/sales/deals", json={"number": "ORD-NI", "title": "t", "counterparty": "c"})
    ).json()
    # заказ на сделке без позиций → _deal_stock_items вернёт [] (ветка «нет позиций»)
    r = await api.post(f"/sales/deals/{deal['id']}/documents", json={"kind": "order"})
    assert r.status_code == 201 and r.json()["kind"] == "order"


async def test_ai_endpoints_404_when_enabled(ai_api):
    # AI включён, но сделки нет → 404 (ветка после проверки feature-flag)
    assert (await ai_api.post("/sales/deals/999999/ai/draft-reply")).status_code == 404
    assert (
        await ai_api.post("/sales/deals/999999/ai/assist", json={"kind": "summary"})
    ).status_code == 404


# --- Защитные ветки: интеграции не подключены (503) ---


async def test_document_503_without_onec(api_no_gateways):
    deal = (
        await api_no_gateways.post("/sales/deals", json={"number": "NO-1", "title": "t", "counterparty": "c"})
    ).json()
    r = await api_no_gateways.post(f"/sales/deals/{deal['id']}/documents", json={"kind": "invoice"})
    assert r.status_code == 503


async def test_decide_503_without_onec(session, api_no_gateways):
    from modules.sales.models import Deal, DealDocument

    deal = Deal(number="DEC-NO", title="t", counterparty="c")
    session.add(deal)
    await session.flush()
    doc = DealDocument(deal_id=deal.id, kind="contract", number="ДГ-DEC", status="pending_approval")
    session.add(doc)
    await session.commit()
    r = await api_no_gateways.post(f"/sales/documents/{doc.id}/decide", json={"approved": True})
    assert r.status_code == 503


async def test_egr_503_without_registry(api_no_gateways):
    assert (await api_no_gateways.get("/integrations/egr/191234567")).status_code == 503


async def test_create_activity_with_explicit_date(api):
    # дата передана явно → ветка без запроса max(Activity.date)
    r = await api.post("/sales/activities", json={"kpi_key": "calls_all", "date": "2026-06-01"})
    assert r.status_code == 201 and r.json()["date"] == "2026-06-01"


async def test_lead_requalify_keeps_routed_status(api):
    lead = (await api.post("/sales/leads", json={"source": "site", "company": "ООО Реквал"})).json()
    await api.post(f"/sales/leads/{lead['id']}/qualify")  # new → qualified
    await api.post(f"/sales/leads/{lead['id']}/route")  # → routed
    # повторная квалификация: статус не «new» → не откатывается на qualified
    r = await api.post(f"/sales/leads/{lead['id']}/qualify")
    assert r.status_code == 200 and r.json()["status"] == "routed"


async def test_kpis_without_activities(session, api):
    from modules.sales.models import KpiTarget

    session.add(KpiTarget(key="solo", title="Одинокий", target=10, unit="count", icon="phone", tone="blue", sort_order=1))
    await session.commit()
    # есть цель, но нет ни одной активности → max(date)=None, ветка без запроса фактов
    item = next(i for i in (await api.get("/sales/kpis")).json() if i["key"] == "solo")
    assert item["actual"] == 0 and item["percent"] == 0
