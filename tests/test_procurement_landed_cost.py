"""Тесты landed cost закупок: заказ с позициями → приёмка → себестоимость per-SKU + фасад.

Закупки — источник истины себестоимости единицы (BYN). На приёмке заказа (``received``) фрахт
разносится на позиции общим движком ``allocate_landed_cost``, результат пишется построчно в
``LandedCost``. Продажи читают его через фасад ядра ``core.services.landed_cost.last_landed_cost``
для расчёта маржи. Открытые заказы с ETA дают sales «в пути». Контракт —
``coordination/procurement-costing-handoff.md`` §7 + указания координатора (PurchaseOrder).
"""
from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from core.domain.models import OutboxEvent
from modules.procurement.landed_cost import LandedCostService
from modules.procurement.models import LandedCost
from modules.procurement.order_edit_commands import PurchaseOrderEditCommand  # noqa: F401

pytestmark = pytest.mark.asyncio

SVC = LandedCostService()


async def _historical_landed_order(api, session, *, lines):
    """Seed only legacy cost inputs no longer accepted by the creation API."""
    from modules.procurement.models import PurchaseOrder, PurchaseOrderLine

    api.headers["X-User"] = "procurement-owner-test"
    order = PurchaseOrder(number="SYNTHETIC-HISTORICAL-COST", supplier="Поставщик", status="ordered")
    session.add(order)
    await session.flush()
    session.add_all([PurchaseOrderLine(order_id=order.id, **line) for line in lines])
    await session.commit()
    books = (await api.get("/accounting/organizations")).json()
    if not books:
        created = await api.post("/accounting/organizations", json={"name": "Synthetic procurement company", "unp": "999999994"})
        assert created.status_code == 201, created.text
        books = [created.json()]
    org = books[0]["id"]
    assigned = await api.post(f"/procurement/organizations/{org}/purchase-ownership", json={
        "kind": "order", "source_id": order.id, "evidence": "Explicit synthetic historical landed-cost fixture"
    })
    assert assigned.status_code == 201, assigned.text
    api.headers["X-Expected-Organization"] = str(org)
    api.headers["X-Expected-Principal"] = "procurement-owner-test"
    return {"id": order.id}


async def _receive(api, order_id):
    org = api.headers["X-Expected-Organization"]
    r = await api.post(f"/procurement/organizations/{org}/orders/{order_id}/edit-commands", json={
        "version": 1, "request_key": str(uuid4()), "order_id": order_id,
        "action": "status", "payload": {"status": "received"}
    })
    assert r.status_code == 200, r.text
    return r.json()


async def _rows(session):
    return (await session.execute(select(LandedCost))).scalars().all()


# ───────────────────────── фиксация на приёмке + распределение ─────────────────────────


async def _scoped_landed_order(api, session, *, lines, freight_byn=0):
    from core.domain.models import Counterparty
    from modules.procurement.models import Supplier
    from modules.procurement.order_creation import PurchaseOrderCreation

    connection = await session.connection()
    await connection.run_sync(lambda sync: PurchaseOrderCreation.__table__.create(sync, checkfirst=True))
    party = Counterparty(name="Поставщик", unp="999999993")
    session.add(party)
    await session.flush()
    session.add(Supplier(counterparty_id=party.id, name=party.name, unp=party.unp, status="active"))
    await session.commit()
    api.headers["X-User"] = "procurement-owner-test"
    org_response = await api.post("/accounting/organizations", json={
        "name": "Synthetic procurement company", "unp": "999999994",
    })
    assert org_response.status_code == 201, org_response.text
    org = org_response.json()["id"]
    options = await api.get(f"/procurement/organizations/{org}/supplier-options", params={"q": party.name})
    assert options.status_code == 200, options.text
    supplier = next(item for item in options.json()["items"] if item["name"] == party.name)
    api.headers["X-Expected-Organization"] = str(org)
    api.headers["X-Expected-Principal"] = "procurement-owner-test"
    created = await api.post(f"/procurement/organizations/{org}/orders", json={
        "request_key": str(uuid4()), "ownership_evidence": "Synthetic landed-cost fixture",
        "request_basis": None, "document": {
            "supplier": supplier["name"], "supplier_id": supplier["id"], "supplier_unp": supplier["unp"],
            "freight_byn": f"{Decimal(str(freight_byn)):.2f}",
            "lines": [{"sku_code": line["sku_code"], "qty": f"{Decimal(str(line['qty'])):.2f}",
                       "goods_value_byn": f"{Decimal(str(line['goods_value_byn'])):.2f}",
                       "weight": f"{Decimal(str(line.get('weight', 0))):.3f}",
                       "volume": f"{Decimal(str(line.get('volume', 0))):.4f}"} for line in lines],
        },
    })
    assert created.status_code == 201, created.text
    return {"id": created.json()["order_id"]}


async def _scoped_landed_next_order(api, session, *, lines):
    from modules.procurement.models import PurchaseOrder

    org = api.headers["X-Expected-Organization"]
    options = await api.get(f"/procurement/organizations/{org}/supplier-options", params={"q": "Поставщик"})
    assert options.status_code == 200, options.text
    supplier = next(item for item in options.json()["items"] if item["name"] == "Поставщик")
    created = await api.post(f"/procurement/organizations/{org}/orders", json={
        "request_key": str(uuid4()), "ownership_evidence": "Synthetic landed-cost fixture",
        "request_basis": None, "document": {
            "supplier": supplier["name"], "supplier_id": supplier["id"], "supplier_unp": supplier["unp"],
            "freight_byn": "0.00",
            "lines": [{"sku_code": line["sku_code"], "qty": f"{Decimal(str(line['qty'])):.2f}",
                       "goods_value_byn": f"{Decimal(str(line['goods_value_byn'])):.2f}",
                       "weight": "0.000", "volume": "0.0000"} for line in lines],
        },
    })
    assert created.status_code == 201, created.text
    order = await session.get(PurchaseOrder, created.json()["order_id"])
    assert order is not None
    return {"id": order.id, "number": order.number}


async def test_receive_fixates_unit_cost_no_freight(api, session):
    order = await _scoped_landed_order(api, session, lines=[{"sku_code": "SKU-1", "qty": 10, "goods_value_byn": 1500}])
    await _receive(api, order["id"])

    rows = await _rows(session)
    assert len(rows) == 1
    row = rows[0]
    assert row.sku_code == "SKU-1"
    assert row.purchase_order_id == order["id"]
    assert row.stage == "actual"  # реальная приёмка (cost-estimate — estimated)
    assert row.unit_landed_cost_byn == Decimal("150.00")  # 1500 / 10, без фрахта
    assert row.shipment_id


async def test_freight_allocated_across_positions_by_weight(api, session):
    """Ключевая денежная фича: фрахт заказа распределяется на позиции (по весу)."""
    order = await _scoped_landed_order(
        api, session,
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
    order = await _historical_landed_order(
        api, session,
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
    order = await _scoped_landed_order(api, session, lines=[{"sku_code": "EMIT-1", "qty": 10, "goods_value_byn": 1500}])
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
    assert Decimal(payload["unit_landed_cost_byn"]) == Decimal("150.00")  # JSON-safe str, value check
    assert payload["purchase_order_id"] == order["id"]
    assert payload["stage"] == "actual"  # реальная приёмка (P4)
    # qty + total — Финансам для landed-маржи (unit×qty)
    assert Decimal(payload["qty"]) == Decimal("10")
    assert Decimal(payload["total_landed_byn"]) == Decimal("1500.00")


async def test_zero_qty_line_skipped(api, session):
    """Позиция с qty=0 не фиксируется (unit неопределён) — не пишем 0, не маскируем дыру."""
    order = await _historical_landed_order(
        api, session,
        lines=[
            {"sku_code": "ZERO", "qty": 0, "goods_value_byn": 100},
            {"sku_code": "OK", "qty": 5, "goods_value_byn": 500},
        ],
    )
    await _receive(api, order["id"])

    codes = {r.sku_code for r in await _rows(session)}
    assert codes == {"OK"}  # ZERO пропущена
    assert await SVC.last_landed_cost(session, "ZERO") is None


async def test_invalid_status_rejected(api, session):
    """Неизвестный статус → 422 (опечатка не должна тихо пропустить фиксацию landed cost)."""
    from modules.procurement.models import PurchaseOrder, Supplier

    order = await _scoped_landed_order(api, session, lines=[{"sku_code": "X", "qty": 1, "goods_value_byn": 100}])
    source = await session.get(PurchaseOrder, order["id"])
    supplier = await session.get(Supplier, source.supplier_id)
    org = api.headers["X-Expected-Organization"]
    r = await api.post(f"/procurement/organizations/{org}/orders", json={
        "request_key": str(uuid4()), "ownership_evidence": "Synthetic invalid status fixture", "request_basis": None,
        "document": {"supplier": supplier.name, "supplier_id": supplier.id, "supplier_unp": supplier.unp,
                     "status": "recieved", "freight_byn": "0.00",
                     "lines": [{"sku_code": "X", "qty": "1.00", "goods_value_byn": "100.00", "weight": "0.000", "volume": "0.0000"}]},
    })
    assert r.status_code == 422, r.text
    assert [(error["loc"], error["type"]) for error in r.json()["detail"]] == [
        (["body", "document", "status"], "extra_forbidden")
    ]
    r = await api.post(f"/procurement/organizations/{org}/orders/{order['id']}/edit-commands", json={
        "version": 1, "request_key": str(uuid4()), "order_id": order["id"],
        "action": "status", "payload": {"status": "bogus"},
    })
    assert r.status_code == 422, r.text
    assert [error["type"] for error in r.json()["detail"]] == ["literal_error"]
    await session.refresh(source)
    assert source.status == "draft"


async def test_repeated_receive_no_duplicate(api, session):
    """Повторная приёмка (received→received, no-op) не плодит дубль и не падает (идемпотентность)."""
    order = await _scoped_landed_order(api, session, lines=[{"sku_code": "SKU-1", "qty": 10, "goods_value_byn": 1500}])
    await _receive(api, order["id"])
    await _receive(api, order["id"])  # received→received — no-op, без новой фиксации

    assert len(await _rows(session)) == 1


# ───────────────────────── фасад чтения ─────────────────────────


async def test_last_landed_cost_returns_dict(api, session):
    order = await _scoped_landed_order(api, session, lines=[{"sku_code": "SKU-9", "qty": 8, "goods_value_byn": 200}])
    await _receive(api, order["id"])

    got = await SVC.last_landed_cost(session, "SKU-9")
    assert got is not None
    assert got["unit_landed_cost_byn"] == Decimal("25.00")  # 200 / 8
    assert got["stage"] == "actual"
    assert got["shipment_id"]
    assert got["fixed_at"] is not None
    assert got["fx_rate"] is None  # в минимальном срезе fx не считаем


async def test_last_landed_cost_none_when_no_row(session):
    """Критично: нет строки → None (не 0, не {}) — иначе спрятали бы дыру в марже."""
    assert await SVC.last_landed_cost(session, "НЕТ-ТАКОГО") is None


async def test_last_landed_cost_returns_latest_for_sku(api, session):
    """Два заказа по одному sku_code → отдаём последний по фиксации."""
    o1 = await _scoped_landed_order(api, session, lines=[{"sku_code": "SKU-7", "qty": 10, "goods_value_byn": 1000}])
    await _receive(api, o1["id"])
    o2 = await _scoped_landed_next_order(api, session, lines=[{"sku_code": "SKU-7", "qty": 10, "goods_value_byn": 2000}])
    await _receive(api, o2["id"])

    got = await SVC.last_landed_cost(session, "SKU-7")
    assert got["unit_landed_cost_byn"] == Decimal("200.00")
    assert got["shipment_id"] == o2["number"]


async def test_batch_returns_key_for_every_input(api, session):
    """Батч обязан вернуть ключ для КАЖДОГО входного кода (None, если строки нет)."""
    order = await _scoped_landed_order(api, session, lines=[{"sku_code": "SKU-A", "qty": 10, "goods_value_byn": 1000}])
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


async def test_open_orders_lists_in_transit_with_eta(api, session):
    from modules.procurement.models import PurchaseOrder

    shipped = await _scoped_landed_order(api, session, lines=[{"sku_code": "SKU-PO", "qty": 5, "goods_value_byn": 500}])
    source = await session.get(PurchaseOrder, shipped["id"])
    shipped["number"] = source.number
    customs = await _scoped_landed_next_order(api, session, lines=[{"sku_code": "SKU-CU", "qty": 5, "goods_value_byn": 500}])
    received = await _scoped_landed_next_order(api, session, lines=[{"sku_code": "SKU-QC", "qty": 5, "goods_value_byn": 500}])
    org = api.headers["X-Expected-Organization"]
    for order, status, eta in [(shipped, "shipped", "2026-08-01"), (customs, "customs", "2026-07-15")]:
        for action, payload in [("header", {"eta_date": eta}), ("status", {"status": status})]:
            response = await api.post(f"/procurement/organizations/{org}/orders/{order['id']}/edit-commands", json={
                "version": 1, "request_key": str(uuid4()), "order_id": order["id"], "action": action, "payload": payload,
            })
            assert response.status_code == 200, response.text
    await _receive(api, received["id"])

    org = api.headers["X-Expected-Organization"]
    response = await api.get(f"/procurement/organizations/{org}/open-orders")
    assert response.status_code == 200, response.text
    rows = response.json()["items"]
    numbers = {o["number"] for o in rows}
    assert numbers == {shipped["number"], customs["number"]}  # received — не открытый
    # Scoped reads use a stable ID keyset; ETA remains explicit data for the UI to sort/filter.
    by_number = {row["number"]: row for row in rows}
    assert by_number[customs["number"]]["eta_date"] == "2026-07-15"
    assert by_number[shipped["number"]]["eta_date"] == "2026-08-01"
