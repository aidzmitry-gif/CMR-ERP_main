"""Тесты MRP-lite: сигнал дефицита склада → авто-черновик заявки на закупку (круг 3).

Реактивная петля wms → procurement: WMS эмитит ``wms.stock.low`` (плоский canonical payload),
relay доставляет подписчику закупок (``on_stock_low``), тот через ``_request_from_deficit``
создаёт ``PurchaseRequest(origin='deficit')``. Идемпотентность: повтор сигнала по той же
позиции не плодит дубль. Тонкий эндпоинт ``/requests/from-deficit`` — отладочный вход поверх
того же хелпера. Фоновый relay в тестах не крутится — гоняем ``relay_once`` вручную.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from core.runtime.app import create_app
from core.runtime.deps import get_session
from core.services.eventbus import EventContext
from modules.procurement.models import PurchaseRequest

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def deficit_app(session):
    """Клиент + core на тест-сессии (для ручного relay подписчика wms.stock.low)."""
    app = create_app()

    async def _override():
        yield session

    app.dependency_overrides[get_session] = _override
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", headers={"X-User-Roles": "director"}
    ) as client:
        yield client, app.state.core


async def _requests(session):
    return (await session.execute(select(PurchaseRequest))).scalars().all()


# ───────────────────────── P1: helper + эндпоинт /requests/from-deficit ─────────────────────────


async def test_from_deficit_endpoint_creates_request(api, session):
    """Эндпоинт создаёт заявку: qty=ceil(reorder_qty), stage='need', origin='deficit', item=sku_title."""
    r = await api.post(
        "/procurement/requests/from-deficit",
        json={"sku_code": "SKU-1", "sku_title": "АКБ 48V 100Ah", "warehouse": "Главный",
              "deficit": 5, "reorder_qty": 20},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["qty"] == 20  # ceil(reorder_qty)
    assert body["stage"] == "need"
    assert body["origin"] == "deficit"
    assert body["item"] == "АКБ 48V 100Ah"  # item := sku_title
    assert body["number"]  # авто-номер проставлен


async def test_from_deficit_falls_back_to_deficit_qty(api):
    """reorder_qty не задан → кол-во = ceil(deficit)."""
    r = await api.post(
        "/procurement/requests/from-deficit",
        json={"sku_code": "SKU-X", "sku_title": "Деталь", "deficit": 7, "reorder_qty": 0},
    )
    assert r.status_code == 201
    assert r.json()["qty"] == 7


async def test_from_deficit_idempotent(api, session):
    """Повтор того же sku среди незакрытых заявок не плодит дубль (вернуть существующую)."""
    payload = {"sku_code": "SKU-DUP", "sku_title": "Повтор", "deficit": 3, "reorder_qty": 10}
    first = (await api.post("/procurement/requests/from-deficit", json=payload)).json()
    second = (await api.post("/procurement/requests/from-deficit", json=payload)).json()
    assert first["id"] == second["id"]  # та же заявка
    deficit_rows = [r for r in await _requests(session) if r.origin == "deficit"]
    assert len(deficit_rows) == 1


async def test_from_deficit_item_falls_back_to_sku_code(api):
    """Без sku_title item := sku_code (fallback)."""
    r = await api.post("/procurement/requests/from-deficit", json={"sku_code": "ONLY-CODE", "deficit": 2})
    assert r.status_code == 201
    assert r.json()["item"] == "ONLY-CODE"


# ───────────────────────── P2: подписка на wms.stock.low ─────────────────────────


async def test_subscription_registered(deficit_app):
    _, core = deficit_app
    handlers = core.event_bus._handlers.get("wms.stock.low", [])
    assert any(h.__name__ == "on_stock_low" for h in handlers)


async def test_stock_low_event_creates_request(deficit_app, session):
    """Диспатч wms.stock.low (плоский payload) → создана PurchaseRequest(origin='deficit')."""
    client, core = deficit_app
    core.event_bus.emit(
        session,
        "wms.stock.low",
        {
            "sku_code": "WMS-1", "sku_title": "Корпус", "warehouse": "Главный",
            "free_qty": 2, "min_qty": 10, "deficit": 8, "reorder_qty": 50,
            "severity": "below_min", "source": "wms.threshold", "entity_ref": "threshold:1",
        },
    )
    await core.event_bus.relay_once(session, EventContext(session, core.services))

    rows = [r for r in await _requests(session) if r.origin == "deficit"]
    assert len(rows) == 1
    assert rows[0].item == "Корпус" and rows[0].qty == 50 and rows[0].stage == "need"


async def test_stock_low_event_idempotent_on_replay(deficit_app, session):
    """Повторная доставка того же сигнала (at-least-once) не плодит дубль заявки."""
    client, core = deficit_app
    payload = {
        "sku_code": "WMS-2", "sku_title": "Плата", "warehouse": "Главный",
        "deficit": 4, "reorder_qty": 12, "severity": "below_min",
        "source": "wms.threshold", "entity_ref": "threshold:2",
    }
    core.event_bus.emit(session, "wms.stock.low", dict(payload))
    core.event_bus.emit(session, "wms.stock.low", dict(payload))  # тот же сигнал ещё раз
    await core.event_bus.relay_once(session, EventContext(session, core.services))

    rows = [r for r in await _requests(session) if r.origin == "deficit" and r.item == "Плата"]
    assert len(rows) == 1


async def test_stock_low_without_sku_code_skipped(deficit_app, session):
    """payload без sku_code → лог и выход (заявка не создаётся, событие не падает)."""
    client, core = deficit_app
    core.event_bus.emit(session, "wms.stock.low", {"sku_title": "Без кода", "deficit": 5})
    await core.event_bus.relay_once(session, EventContext(session, core.services))
    assert [r for r in await _requests(session) if r.origin == "deficit"] == []


# ───────────────────────── P8: origin в PurchaseRequestOut + бейдж на доске ─────────────────────────


async def test_origin_exposed_in_requests_and_board(api):
    """PurchaseRequestOut несёт origin; на доске карточка авто-заявки имеет status_tag-бейдж."""
    await api.post(
        "/procurement/requests/from-deficit",
        json={"sku_code": "SKU-B", "sku_title": "Бейдж", "deficit": 1, "reorder_qty": 5},
    )
    # ручная заявка — без origin (бейджа быть не должно)
    await api.post("/procurement/requests", json={"supplier": "S", "item": "Ручная", "qty": 1})

    flat = (await api.get("/procurement/requests")).json()
    by_item = {r["item"]: r for r in flat}
    assert by_item["Бейдж"]["origin"] == "deficit"
    assert by_item["Ручная"]["origin"] == ""

    board = (await api.get("/procurement/board")).json()
    cards = {c["title"]: c for s in board["stages"] for c in s["cards"]}
    assert cards["Бейдж"]["status_tag"] == "Авто: дефицит склада"
    assert cards["Ручная"]["status_tag"] == ""  # ручная — без бейджа
