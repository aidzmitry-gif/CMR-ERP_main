"""Тесты плана сбора машины (Китай → Минск): шаблон длительностей по способу перевозки +
обратный waterfall от «В Минске до» + план/факт по этапам.

Модель из реального плана заказчика: Контейнер ≈112 дн / Машина ≈83 дн; каждый этап завершается
к дедлайну, последний (растоможка) — в дату «В Минске до». Факт ⑦ приходит из приёмки заказа.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from modules.procurement.plan import STAGE_ORDER

pytestmark = pytest.mark.asyncio


# ───────────────────────── справочник способов перевозки ─────────────────────────


async def test_transport_methods_seeded(api):
    rows = (await api.get("/procurement/transport-methods")).json()
    by = {m["code"]: m for m in rows}
    assert by["container"]["total_days"] == 112
    assert by["truck"]["total_days"] == 83
    assert by["container"]["durations"]["to_minsk"] == 42
    assert by["truck"]["durations"]["to_minsk"] == 20


async def test_transport_method_edit_durations(api):
    await api.get("/procurement/transport-methods")  # сид
    r = await api.patch("/procurement/transport-methods/truck", json={"durations": {"to_minsk": 25}})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["durations"]["to_minsk"] == 25
    assert body["total_days"] == 88  # 83 − 20 + 25
    assert body["durations"]["production"] == 14  # прочие этапы не затёрты (мерж)


async def test_transport_method_edit_404(api):
    await api.get("/procurement/transport-methods")
    assert (await api.patch("/procurement/transport-methods/plane", json={"name": "Самолёт"})).status_code == 404


# ───────────────────────── план машины (PurchaseOrder) ─────────────────────────


async def _order(api, **over):
    body = {"supplier": "S", "lines": [{"sku_code": "A", "qty": 1, "goods_value_byn": 100}]}
    body.update(over)
    r = await api.post("/procurement/orders", json=body)
    assert r.status_code == 201, r.text
    return r.json()


async def test_plan_order_container_backward(api):
    o = await _order(api)
    target = "2026-10-01"
    r = await api.post(
        f"/procurement/orders/{o['id']}/plan",
        json={"transport_method_code": "container", "target_arrival_date": target},
    )
    assert r.status_code == 200, r.text
    plan = r.json()
    assert plan["transport_method_code"] == "container"
    assert plan["target_arrival_date"] == target
    assert plan["total_days"] == 112
    assert plan["start_date"] == (date(2026, 10, 1) - timedelta(days=112)).isoformat()
    by = {m["stage"]: m for m in plan["milestones"]}
    assert by["customs"]["planned_date"] == target  # последний этап = «В Минске до»
    assert by["collection"]["planned_date"] == (date(2026, 10, 1) - timedelta(days=84)).isoformat()
    assert [m["stage"] for m in plan["milestones"]] == STAGE_ORDER
    # факт ещё не наступил
    assert all(m["actual_date"] is None for m in plan["milestones"])


async def test_get_plan_returns_saved(api):
    o = await _order(api)
    await api.post(
        f"/procurement/orders/{o['id']}/plan",
        json={"transport_method_code": "truck", "target_arrival_date": "2026-09-01"},
    )
    plan = (await api.get(f"/procurement/orders/{o['id']}/plan")).json()
    assert plan["total_days"] == 83
    assert len(plan["milestones"]) == len(STAGE_ORDER)


async def test_replan_recomputes_but_keeps_actual(api):
    """Пересчёт плана обновляет плановые даты, но факт (actual_date) приёмки сохраняется."""
    o = await _order(api)
    await api.post(
        f"/procurement/orders/{o['id']}/plan",
        json={"transport_method_code": "container", "target_arrival_date": "2026-10-01"},
    )
    # приёмка проставляет факт ⑦ (растоможка/В Минске)
    await api.patch(f"/procurement/orders/{o['id']}", json={"status": "received"})
    after_receive = (await api.get(f"/procurement/orders/{o['id']}/plan")).json()
    customs_actual = {m["stage"]: m["actual_date"] for m in after_receive["milestones"]}["customs"]
    assert customs_actual is not None  # факт прихода зафиксирован

    # пересчёт на другой дедлайн — план меняется, факт остаётся
    r = await api.post(
        f"/procurement/orders/{o['id']}/plan",
        json={"transport_method_code": "container", "target_arrival_date": "2026-11-01"},
    )
    by = {m["stage"]: m for m in r.json()["milestones"]}
    assert by["customs"]["planned_date"] == "2026-11-01"  # план пересчитан
    assert by["customs"]["actual_date"] == customs_actual  # факт сохранён


async def test_received_marks_arrival_fact(api):
    """Приёмка машины с планом проставляет факт последнего этапа (⑦ В Минске)."""
    o = await _order(api)
    await api.post(
        f"/procurement/orders/{o['id']}/plan",
        json={"transport_method_code": "truck", "target_arrival_date": "2026-09-01"},
    )
    await api.patch(f"/procurement/orders/{o['id']}", json={"status": "received"})
    plan = (await api.get(f"/procurement/orders/{o['id']}/plan")).json()
    last = next(m for m in plan["milestones"] if m["stage"] == STAGE_ORDER[-1])
    assert last["actual_date"] is not None


async def test_plan_uses_edited_durations(api):
    """Правка способа перевозки доходит до плана машины (план читает строку из БД, не код-дефолт)."""
    o = await _order(api)
    await api.patch("/procurement/transport-methods/truck", json={"durations": {"to_minsk": 25}})
    plan = (await api.post(
        f"/procurement/orders/{o['id']}/plan",
        json={"transport_method_code": "truck", "target_arrival_date": "2026-10-01"},
    )).json()
    assert plan["total_days"] == 88  # 83 − 20 + 25
    by = {m["stage"]: m for m in plan["milestones"]}
    assert by["to_minsk"]["duration_days"] == 25
    assert plan["start_date"] == (date(2026, 10, 1) - timedelta(days=88)).isoformat()


async def test_replan_keeps_intermediate_actual(api, session):
    """Пересчёт сохраняет факт ЛЮБОГО этапа, не только последнего (контракт «факт сохраняется»)."""
    from sqlalchemy import select

    from modules.procurement.models import PurchaseOrderMilestone

    o = await _order(api)
    await api.post(
        f"/procurement/orders/{o['id']}/plan",
        json={"transport_method_code": "container", "target_arrival_date": "2026-10-01"},
    )
    # факт промежуточного этапа (производство) — как будто пришёл сигнал
    row = (await session.execute(
        select(PurchaseOrderMilestone).where(
            PurchaseOrderMilestone.order_id == o["id"],
            PurchaseOrderMilestone.stage == "production",
        )
    )).scalars().first()
    row.actual_date = date(2026, 8, 1)
    await session.commit()

    r = await api.post(
        f"/procurement/orders/{o['id']}/plan",
        json={"transport_method_code": "container", "target_arrival_date": "2026-11-01"},
    )
    by = {m["stage"]: m for m in r.json()["milestones"]}
    assert by["production"]["actual_date"] == "2026-08-01"  # факт промежуточного этапа сохранён
    assert by["production"]["planned_date"] != "2026-08-01"  # план при этом пересчитан


async def test_plan_unknown_method_404(api):
    o = await _order(api)
    r = await api.post(
        f"/procurement/orders/{o['id']}/plan",
        json={"transport_method_code": "plane", "target_arrival_date": "2026-10-01"},
    )
    assert r.status_code == 404


async def test_plan_unknown_order_404(api):
    r = await api.post(
        "/procurement/orders/99999/plan",
        json={"transport_method_code": "container", "target_arrival_date": "2026-10-01"},
    )
    assert r.status_code == 404
    assert (await api.get("/procurement/orders/99999/plan")).status_code == 404
