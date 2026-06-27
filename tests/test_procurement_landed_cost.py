"""Тесты landed cost закупок: заказ с позициями → приёмка → себестоимость per-SKU + фасад.

Закупки — источник истины себестоимости единицы (BYN). На приёмке заказа (``received``) фрахт
разносится на позиции общим движком ``allocate_landed_cost``, результат пишется построчно в
``LandedCost``. Продажи читают его через фасад ядра ``core.services.landed_cost.last_landed_cost``
для расчёта маржи. Открытые заказы с ETA дают sales «в пути». Контракт —
``coordination/procurement-costing-handoff.md`` §7 + указания координатора (PurchaseOrder).
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from core.domain.models import OutboxEvent
from modules.procurement.landed_cost import LandedCostService
from modules.procurement.models import LandedCost

pytestmark = pytest.mark.asyncio

SVC = LandedCostService()


async def _order(api, **fields):
    payload = {"supplier": "Поставщик", "lines": [{"sku_code": "A", "qty": 10, "goods_value_byn": 1500}]}
    payload.update(fields)
    r = await api.post("/procurement/orders", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


async def _receive(api, order_id):
    r = await api.patch(f"/procurement/orders/{order_id}", json={"status": "received"})
    assert r.status_code == 200, r.text
    return r.json()


async def _rows(session):
    return (await session.execute(select(LandedCost))).scalars().all()


# ───────────────────────── фиксация на приёмке + распределение ─────────────────────────


async def test_receive_fixates_unit_cost_no_freight(api, session):
    order = await _order(api, lines=[{"sku_code": "SKU-1", "qty": 10, "goods_value_byn": 1500}])
    await _receive(api, order["id"])

    rows = await _rows(session)
    assert len(rows) == 1
    row = rows[0]
    assert row.sku_code == "SKU-1"
    assert row.purchase_order_id == order["id"]
    assert row.stage == "estimated"
    assert row.unit_landed_cost_byn == Decimal("150.00")  # 1500 / 10, без фрахта
    assert row.shipment_id


async def test_freight_allocated_across_positions_by_weight(api, session):
    """Ключевая денежная фича: фрахт заказа распределяется на позиции (по весу)."""
    order = await _order(
        api,
        freight_byn=200,
        lines=[
            {"sku_code": "A", "qty": 10, "goods_value_byn": 100, "weight": 6},
            {"sku_code": "B", "qty": 30, "goods_value_byn": 300, "weight": 14},
        ],
    )
    await _receive(api, order["id"])

    # фрахт 200 по весу 6/20 и 14/20 → 60 / 140; landed 160 / 440; unit 16.00 / 14.67
    a = await SVC.last_landed_cost(session, "A")
    b = await SVC.last_landed_cost(session, "B")
    assert a["unit_landed_cost_byn"] == Decimal("16.00")
    assert b["unit_landed_cost_byn"] == Decimal("14.67")


async def test_duplicate_sku_lines_aggregated(api, session):
    """Две позиции с одним sku_code → одна строка LandedCost (агрегация qty/стоимости)."""
    order = await _order(
        api,
        lines=[
            {"sku_code": "DUP", "qty": 4, "goods_value_byn": 400},
            {"sku_code": "DUP", "qty": 6, "goods_value_byn": 600},
        ],
    )
    await _receive(api, order["id"])

    rows = [r for r in await _rows(session) if r.sku_code == "DUP"]
    assert len(rows) == 1
    assert rows[0].unit_landed_cost_byn == Decimal("100.00")  # (400+600) / (4+6)


async def test_receive_emits_landed_cost_calculated(api, session):
    """Приёмка эмитит procurement.landed_cost.calculated по каждой номенклатуре (push для sales)."""
    order = await _order(api, lines=[{"sku_code": "EMIT-1", "qty": 10, "goods_value_byn": 1500}])
    await _receive(api, order["id"])

    events = (
        await session.execute(
            select(OutboxEvent).where(
                OutboxEvent.event_type == "procurement.landed_cost.calculated"
            )
        )
    ).scalars().all()
    assert len(events) == 1
    payload = events[0].payload
    assert payload["sku_code"] == "EMIT-1"
    assert payload["unit_landed_cost_byn"] == "150.00"  # JSON-safe (Decimal → str)
    assert payload["purchase_order_id"] == order["id"]
    # qty + total — Финансам для landed-маржи (unit×qty)
    assert Decimal(payload["qty"]) == Decimal("10")
    assert Decimal(payload["total_landed_byn"]) == Decimal("1500.00")


async def test_zero_qty_line_skipped(api, session):
    """Позиция с qty=0 не фиксируется (unit неопределён) — не пишем 0, не маскируем дыру."""
    order = await _order(
        api,
        lines=[
            {"sku_code": "ZERO", "qty": 0, "goods_value_byn": 100},
            {"sku_code": "OK", "qty": 5, "goods_value_byn": 500},
        ],
    )
    await _receive(api, order["id"])

    codes = {r.sku_code for r in await _rows(session)}
    assert codes == {"OK"}  # ZERO пропущена
    assert await SVC.last_landed_cost(session, "ZERO") is None


async def test_invalid_status_rejected(api):
    """Неизвестный статус → 422 (опечатка не должна тихо пропустить фиксацию landed cost)."""
    r = await api.post(
        "/procurement/orders",
        json={"supplier": "S", "status": "recieved", "lines": [{"sku_code": "X", "qty": 1}]},
    )
    assert r.status_code == 422
    order = await _order(api)
    r = await api.patch(f"/procurement/orders/{order['id']}", json={"status": "bogus"})
    assert r.status_code == 422


async def test_repeated_receive_no_duplicate(api, session):
    """Повторная приёмка (received→received, no-op) не плодит дубль и не падает (идемпотентность)."""
    order = await _order(api, lines=[{"sku_code": "SKU-1", "qty": 10, "goods_value_byn": 1500}])
    await _receive(api, order["id"])
    await _receive(api, order["id"])  # received→received — no-op, без новой фиксации

    assert len(await _rows(session)) == 1


# ───────────────────────── фасад чтения ─────────────────────────


async def test_last_landed_cost_returns_dict(api, session):
    order = await _order(api, lines=[{"sku_code": "SKU-9", "qty": 8, "goods_value_byn": 200}])
    await _receive(api, order["id"])

    got = await SVC.last_landed_cost(session, "SKU-9")
    assert got is not None
    assert got["unit_landed_cost_byn"] == Decimal("25.00")  # 200 / 8
    assert got["stage"] == "estimated"
    assert got["shipment_id"]
    assert got["fixed_at"] is not None
    assert got["fx_rate"] is None  # в минимальном срезе fx не считаем


async def test_last_landed_cost_none_when_no_row(session):
    """Критично: нет строки → None (не 0, не {}) — иначе спрятали бы дыру в марже."""
    assert await SVC.last_landed_cost(session, "НЕТ-ТАКОГО") is None


async def test_last_landed_cost_returns_latest_for_sku(api, session):
    """Два заказа по одному sku_code → отдаём последний по фиксации."""
    o1 = await _order(api, lines=[{"sku_code": "SKU-7", "qty": 10, "goods_value_byn": 1000}])
    await _receive(api, o1["id"])
    o2 = await _order(api, lines=[{"sku_code": "SKU-7", "qty": 10, "goods_value_byn": 2000}])
    await _receive(api, o2["id"])

    got = await SVC.last_landed_cost(session, "SKU-7")
    assert got["unit_landed_cost_byn"] == Decimal("200.00")
    assert got["shipment_id"] == o2["number"]


async def test_batch_returns_key_for_every_input(api, session):
    """Батч обязан вернуть ключ для КАЖДОГО входного кода (None, если строки нет)."""
    order = await _order(api, lines=[{"sku_code": "SKU-A", "qty": 10, "goods_value_byn": 1000}])
    await _receive(api, order["id"])

    got = await SVC.last_landed_cost_batch(session, ["SKU-A", "SKU-B", "SKU-A"])
    assert set(got.keys()) == {"SKU-A", "SKU-B"}
    assert got["SKU-A"]["unit_landed_cost_byn"] == Decimal("100.00")
    assert got["SKU-B"] is None


async def test_batch_empty_input(session):
    assert await SVC.last_landed_cost_batch(session, []) == {}


async def test_gateway_registered(services):
    """register() кладёт реализацию в фасад ядра (не None после load_modules)."""
    assert services.landed_cost is not None
    assert isinstance(services.landed_cost, LandedCostService)


# ───────────────────────── открытые заказы с ETA ─────────────────────────


async def test_open_orders_lists_in_transit_with_eta(api):
    await _order(api, number="PO-SHIP", status="shipped", eta_date="2026-08-01",
                 lines=[{"sku_code": "SKU-PO", "qty": 5, "goods_value_byn": 500}])
    await _order(api, number="PO-CUST", status="customs", eta_date="2026-07-15",
                 lines=[{"sku_code": "SKU-CU", "qty": 5, "goods_value_byn": 500}])
    received = await _order(api, number="PO-DONE", status="ordered",
                            lines=[{"sku_code": "SKU-QC", "qty": 5, "goods_value_byn": 500}])
    await _receive(api, received["id"])

    rows = (await api.get("/procurement/open-orders")).json()
    numbers = {o["number"] for o in rows}
    assert numbers == {"PO-SHIP", "PO-CUST"}  # received — не открытый
    # ближайший ETA первым (15 июля < 1 августа), позиции отданы
    assert rows[0]["number"] == "PO-CUST"
    assert rows[0]["eta_date"] == "2026-07-15"
    assert rows[0]["lines"][0]["sku_code"] == "SKU-CU"
