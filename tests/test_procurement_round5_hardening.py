"""Круг 5 — тест-харднинг закупок (надёжность сделанного в кругах 2-4, НЕ фичи).

Каждый кейс закрепляет конкретную дыру из докладов и зависит от реальной защитной логики
(удали гард — тест упадёт), а не тавтология. Фоновый relay в тестах не крутится — гоняем
``relay_once`` вручную на той же in-memory сессии.

Кейсы: (1) MRP-lite дедуп wms.stock.low между проходами relay; (2) обратный waterfall при
недостижимом сроке (срок−буфер < сегодня) — риск + валидные (прошлые) даты, без падения и None;
(3) факт приёмки не перетирается более поздней оценкой в фасаде себестоимости; (4) reference→landed
идемпотентен между батчами (одна строка, стабильное значение); (5) повторный resolve претензии не
шлёт второе событие (finance не задваивает).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

import core.services.sku_master as sku_master_mod
from core.domain.models import OutboxEvent, Sku
from core.runtime.app import create_app
from core.runtime.deps import get_session
from core.services.eventbus import EventContext
from modules.procurement.models import LandedCost, PurchaseRequest

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def app2(session):
    """Клиент + core на тест-сессии (для ручного relay подписчиков)."""
    app = create_app()

    async def _override():
        yield session

    app.dependency_overrides[get_session] = _override
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", headers={"X-User-Roles": "director"}
    ) as client:
        yield client, app.state.core


async def _relay(core, session):
    await core.event_bus.relay_once(session, EventContext(session, core.services))


def _patch_duty(monkeypatch, pct):
    calls = {"n": 0}

    async def fake(session, sku_code, on_date=None):
        calls["n"] += 1
        return {"duty_pct": pct}

    monkeypatch.setattr(sku_master_mod, "landed_inputs", fake)
    return calls


# ───────────────────────── 1. MRP-lite дедуп между проходами relay ─────────────────────────


async def test_stock_low_dedup_across_relay_cycles(app2, session):
    """Два `wms.stock.low` по одному SKU в РАЗНЫХ проходах relay (at-least-once redelivery с
    коммитом между) → один черновик: повтор находит уже закоммиченную заявку. (Внутри одного
    батча уже покрыто test_procurement_deficit; здесь — пост-commit путь.)"""
    client, core = app2
    payload = {"sku_code": "X1", "sku_title": "Корпус X", "warehouse": "Главный",
               "deficit": 4, "reorder_qty": 12, "entity_ref": "threshold:X1"}
    core.event_bus.emit(session, "wms.stock.low", dict(payload))
    await _relay(core, session)  # батч 1 — создаёт и коммитит
    core.event_bus.emit(session, "wms.stock.low", dict(payload))
    await _relay(core, session)  # батч 2 — должен найти закоммиченную, не плодить дубль
    rows = [r for r in (await session.execute(select(PurchaseRequest))).scalars().all()
            if r.origin == "deficit" and r.item == "Корпус X"]
    assert len(rows) == 1


# ───────────────────────── 2. Обратный waterfall: недостижимый срок ─────────────────────────


async def test_plan_unreachable_deadline_risk_no_invalid_dates(app2, session):
    """Срок клиента − буфер < сегодня (физически не успеть) → at_risk, валидные (прошлые) даты,
    без падения и без None/отрицательных дат."""
    client, core = app2
    o = (await client.post(
        "/procurement/orders",
        json={"supplier": "S", "lines": [{"sku_code": "A", "qty": 5, "goods_value_byn": 500}]},
    )).json()
    today = datetime.now(timezone.utc).date()
    soon = (today + timedelta(days=1)).isoformat()  # срок завтра → срок−буфер(3) = позавчера
    core.event_bus.emit(session, "sales.deal.ship_deadline.set", {
        "deal_id": 1, "number": "СД-1", "counterparty": "К", "ship_deadline": soon,
        "items": [{"sku_code": "A", "qty": 5}],
    })
    await _relay(core, session)
    r = await client.post(f"/procurement/orders/{o['id']}/plan",
                          json={"transport_method_code": "truck"})  # target авто = срок−буфер
    assert r.status_code == 200, r.text
    plan = r.json()
    assert plan["at_risk"] is True
    assert plan["required_arrival"] < today.isoformat()  # крайний приход уже в прошлом
    dates = [m["planned_date"] for m in plan["milestones"]]
    assert all(d is not None for d in dates)  # ни одной None/пропущенной даты
    assert dates == sorted(dates)  # монотонный обратный waterfall (по возрастанию)
    assert plan["start_date"] is not None and plan["start_date"] < dates[0]  # старт раньше первого этапа


# ───────────────────────── 3. estimated не перетирает actual ─────────────────────────


async def test_actual_receipt_not_overwritten_by_later_estimate(app2, session, monkeypatch):
    """Факт приёмки (actual) важнее более ПОЗДНЕЙ плановой оценки в фасаде: оценка по второму
    (открытому) заказу не «откатывает» себестоимость к плановой."""
    client, core = app2
    session.add(Sku(code="A", title="A"))
    await session.commit()
    # заказ 1 — принят → actual (goods 1000 / qty 10, фрахт 0 → 100, без пошлины: Горизонт 2)
    o1 = (await client.post("/procurement/orders",
          json={"supplier": "S", "lines": [{"sku_code": "A", "qty": 10, "goods_value_byn": 1000}]})).json()
    assert (await client.patch(f"/procurement/orders/{o1['id']}", json={"status": "received"})).status_code == 200
    # заказ 2 — открыт (в пути) → база для плановой оценки
    o2 = (await client.post("/procurement/orders",
          json={"supplier": "S", "lines": [{"sku_code": "A", "qty": 10, "goods_value_byn": 1000}]})).json()
    assert (await client.patch(f"/procurement/orders/{o2['id']}", json={"status": "ordered"})).status_code == 200
    _patch_duty(monkeypatch, 10.0)  # оценка с пошлиной = 110 > факт 100
    core.event_bus.emit(session, "reference.sku.changed",
                        {"ref_key": "core.skus", "entity_ref": "sku:A"})
    await _relay(core, session)  # пишет estimated 110, fixed_at новее actual
    facade = core.services.landed_cost
    cur = await facade.last_landed_cost(session, "A")
    assert cur["stage"] == "actual" and cur["unit_landed_cost_byn"] == Decimal("100.0000")
    # обе строки существуют (не задвоение одной): actual + estimated
    rows = (await session.execute(select(LandedCost).where(LandedCost.sku_code == "A"))).scalars().all()
    assert {x.stage for x in rows} == {"actual", "estimated"}


# ───────────────────────── 4. reference→landed идемпотентен между батчами ─────────────────────────


async def test_reference_recompute_idempotent_across_batches(app2, session, monkeypatch):
    """Повторный одиночный `reference.sku.changed` в новом проходе relay → та же одна строка
    estimated, стабильное значение (upsert по purchase_order_id IS NULL, не плодим дубль)."""
    client, core = app2
    o = (await client.post("/procurement/orders",
         json={"supplier": "S", "lines": [{"sku_code": "A", "qty": 10, "goods_value_byn": 1000}]})).json()
    assert (await client.patch(f"/procurement/orders/{o['id']}", json={"status": "ordered"})).status_code == 200
    calls = _patch_duty(monkeypatch, 10.0)
    for _ in range(3):  # три отдельных прохода relay (отдельные батчи)
        core.event_bus.emit(session, "reference.sku.changed",
                            {"ref_key": "core.skus", "entity_ref": "sku:A"})
        await _relay(core, session)
    rows = (await session.execute(
        select(LandedCost).where(LandedCost.sku_code == "A", LandedCost.stage == "estimated")
    )).scalars().all()
    assert len(rows) == 1  # одна строка, не три
    assert rows[0].unit_landed_cost_byn == Decimal("110.0000")  # значение стабильно (идемпотентно)
    assert calls["n"] == 3  # пересчёт честно отрабатывает каждый батч (дедуп — внутрибатчевый)


# ───────────────────────── 5. claim.resolved — повтор без дубль-эффекта ─────────────────────────


async def test_claim_reresolve_emits_event_once(app2, session):
    """Повторный resolve уже закрытой претензии НЕ шлёт второе `procurement.claim.resolved`
    (иначе finance задвоит сумму). Гард `was_closed` — закрепляем."""
    client, core = app2
    claim = (await client.post("/procurement/claims",
             json={"supplier": "S", "item": "Брак", "claim_type": "брак", "amount_byn": 500})).json()
    body = {"status": "resolved", "resolution": "компенсация"}
    assert (await client.patch(f"/procurement/claims/{claim['id']}", json=body)).status_code == 200
    assert (await client.patch(f"/procurement/claims/{claim['id']}", json=body)).status_code == 200  # повтор
    events = (await session.execute(
        select(OutboxEvent).where(OutboxEvent.event_type == "procurement.claim.resolved")
    )).scalars().all()
    assert len(events) == 1  # эмит ровно раз, несмотря на два resolve
