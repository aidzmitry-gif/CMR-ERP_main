"""Тесты жизненного цикла заказа: машина состояний + события + приход на склад по позициям +
редактор состава (позиции, landed-preview).

draft→ordered→shipped→customs→received (вперёд со скипами можно, назад — 422). На каждом
переходе — ``procurement.order.status_changed``; на приёмке — фиксация landed cost +
``procurement.received`` ПО КАЖДОЙ позиции (для wms).
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from core.domain.models import OutboxEvent
from modules.procurement.models import LandedCost

pytestmark = pytest.mark.asyncio


async def _order(api, **over):
    body = {"supplier": "S", "lines": [{"sku_code": "A", "qty": 10, "goods_value_byn": 1000}]}
    body.update(over)
    r = await api.post("/procurement/orders", json=body)
    assert r.status_code == 201, r.text
    return r.json()


async def _events(session, etype):
    return [e for e in (await session.execute(select(OutboxEvent))).scalars().all() if e.event_type == etype]


async def test_new_order_is_draft_not_open(api):
    """Новый заказ — draft (черновик), НЕ в открытых (sales не видит «в пути»)."""
    o = await _order(api)
    assert o["status"] == "draft"
    open_ids = {x["id"] for x in (await api.get("/procurement/open-orders")).json()}
    assert o["id"] not in open_ids


async def test_legal_transitions_emit_events(api, session):
    o = await _order(api)
    for st in ("ordered", "shipped", "customs"):
        r = await api.patch(f"/procurement/orders/{o['id']}", json={"status": st})
        assert r.status_code == 200 and r.json()["status"] == st
    changes = await _events(session, "procurement.order.status_changed")
    assert [e.payload["to"] for e in changes] == ["ordered", "shipped", "customs"]
    assert changes[0].payload["from"] == "draft"


async def test_backward_transition_rejected(api):
    o = await _order(api, status="shipped")
    r = await api.patch(f"/procurement/orders/{o['id']}", json={"status": "ordered"})
    assert r.status_code == 422  # откат назад запрещён


async def test_cancel_allowed_but_not_after_received(api):
    o = await _order(api, status="ordered")
    assert (await api.patch(f"/procurement/orders/{o['id']}", json={"status": "cancelled"})).status_code == 200
    o2 = await _order(api, status="received")  # создан принятым
    assert (await api.patch(f"/procurement/orders/{o2['id']}", json={"status": "cancelled"})).status_code == 409


async def test_received_emits_per_line_goods_received(api, session):
    """Приёмка заказа эмитит procurement.received ПО КАЖДОЙ позиции (приход на склад)."""
    o = await _order(
        api,
        freight_byn=200,
        lines=[
            {"sku_code": "A", "qty": 10, "goods_value_byn": 100, "weight": 6},
            {"sku_code": "B", "qty": 30, "goods_value_byn": 300, "weight": 14},
        ],
    )
    await api.patch(f"/procurement/orders/{o['id']}", json={"status": "received"})

    received = await _events(session, "procurement.received")
    by_sku = {e.payload["sku_code"]: e.payload for e in received}
    assert set(by_sku) == {"A", "B"}
    assert by_sku["A"]["qty"] == 10 and by_sku["B"]["qty"] == 30
    assert by_sku["A"]["warehouse"] == "Главный"
    assert by_sku["A"]["entity_ref"].startswith(f"purchase_order:{o['id']}:")
    assert by_sku["A"]["unit_landed_cost_byn"]  # себестоимость проставлена
    # landed cost зафиксирован (per-SKU)
    assert len((await session.execute(select(LandedCost))).scalars().all()) == 2


# ───────────────────── редактор состава (П.10) ─────────────────────


async def test_add_and_delete_line(api):
    o = await _order(api, lines=[{"sku_code": "A", "qty": 1, "goods_value_byn": 100}])
    r = await api.post(f"/procurement/orders/{o['id']}/lines", json={"sku_code": "B", "qty": 2, "goods_value_byn": 200})
    assert r.status_code == 201
    body = r.json()
    assert {ln["sku_code"] for ln in body["lines"]} == {"A", "B"}

    line_b = next(ln for ln in body["lines"] if ln["sku_code"] == "B")
    r = await api.delete(f"/procurement/orders/{o['id']}/lines/{line_b['id']}")
    assert r.status_code == 200
    assert {ln["sku_code"] for ln in r.json()["lines"]} == {"A"}


async def test_cannot_edit_received_order(api):
    o = await _order(api, status="received", lines=[{"sku_code": "A", "qty": 1, "goods_value_byn": 100}])
    r = await api.post(f"/procurement/orders/{o['id']}/lines", json={"sku_code": "B", "qty": 1})
    assert r.status_code == 409  # принятый заказ не редактируется


async def test_update_header_freight_and_eta(api):
    o = await _order(
        api,
        lines=[
            {"sku_code": "A", "qty": 10, "goods_value_byn": 100, "weight": 6},
            {"sku_code": "B", "qty": 30, "goods_value_byn": 300, "weight": 14},
        ],
    )
    r = await api.patch(f"/procurement/orders/{o['id']}/header", json={"freight_byn": 200, "eta_date": "2026-09-01"})
    assert r.status_code == 200
    assert r.json()["freight_byn"] == 200.0 and r.json()["eta_date"] == "2026-09-01"
    # landed-preview учитывает новый фрахт (200 по весу → A unit 16.00)
    prev = (await api.get(f"/procurement/orders/{o['id']}/landed-preview")).json()
    by = {ln["sku_code"]: ln for ln in prev["lines"]}
    assert by["A"]["unit_landed_cost_byn"] == 16.0


async def test_update_header_received_409(api):
    o = await _order(api, status="received", lines=[{"sku_code": "A", "qty": 1, "goods_value_byn": 100}])
    r = await api.patch(f"/procurement/orders/{o['id']}/header", json={"freight_byn": 50})
    assert r.status_code == 409


async def test_freight_partial_weight_falls_back_to_value(api):
    """Если вес задан НЕ у всех позиций — фрахт по стоимости (иначе позиция без веса получит 0)."""
    o = await _order(
        api,
        freight_byn=300,
        lines=[
            {"sku_code": "HEAVY", "qty": 1, "goods_value_byn": 100, "weight": 10},
            {"sku_code": "LIGHT", "qty": 1, "goods_value_byn": 1000, "weight": 0},  # вес не заполнен
        ],
    )
    prev = (await api.get(f"/procurement/orders/{o['id']}/landed-preview")).json()
    by = {ln["sku_code"]: ln for ln in prev["lines"]}
    # по стоимости (100/1100, 1000/1100): обе получают фрахт, LIGHT не обнулён
    assert by["HEAVY"]["allocated_byn"] == 27.27
    assert by["LIGHT"]["allocated_byn"] == 272.73


async def test_negative_freight_rejected(api):
    r = await api.post(
        "/procurement/orders",
        json={"freight_byn": -100, "lines": [{"sku_code": "A", "qty": 1, "goods_value_byn": 100}]},
    )
    assert r.status_code == 422  # отрицательный фрахт → невалидно


async def test_cancelled_order_not_editable(api):
    o = await _order(api, status="ordered", lines=[{"sku_code": "A", "qty": 1, "goods_value_byn": 100}])
    await api.patch(f"/procurement/orders/{o['id']}", json={"status": "cancelled"})
    r = await api.post(f"/procurement/orders/{o['id']}/lines", json={"sku_code": "B", "qty": 1})
    assert r.status_code == 409  # отменённый заказ — терминальный, не редактируется


async def test_cannot_create_cancelled(api):
    r = await api.post("/procurement/orders", json={"status": "cancelled", "lines": []})
    assert r.status_code == 422


async def test_landed_preview_no_fixation(api, session):
    """landed-preview считает распределение БЕЗ фиксации (строк LandedCost не появляется)."""
    o = await _order(
        api,
        freight_byn=200,
        lines=[
            {"sku_code": "A", "qty": 10, "goods_value_byn": 100, "weight": 6},
            {"sku_code": "B", "qty": 30, "goods_value_byn": 300, "weight": 14},
        ],
    )
    prev = (await api.get(f"/procurement/orders/{o['id']}/landed-preview")).json()
    by_sku = {ln["sku_code"]: ln for ln in prev["lines"]}
    # фрахт 200 по весу → A: landed 160 unit 16.00; B: landed 440 unit 14.67
    assert by_sku["A"]["unit_landed_cost_byn"] == 16.0
    assert by_sku["B"]["unit_landed_cost_byn"] == 14.67
    assert prev["total_landed_byn"] == 600.0
    # фиксации НЕ было
    assert (await session.execute(select(LandedCost))).scalars().all() == []
