"""Тесты жизненного цикла заказа: машина состояний + события + приход на склад по позициям +
редактор состава (позиции, landed-preview).

draft→ordered→shipped→customs→received (вперёд со скипами можно, назад — 422). На каждом
переходе — ``procurement.order.status_changed``; на приёмке — фиксация landed cost +
``procurement.received`` ПО КАЖДОЙ позиции (для wms).
"""
from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select

from core.domain.models import Counterparty, OutboxEvent
from modules.procurement.models import LandedCost, PurchaseOrder, Supplier
from modules.procurement.order_creation import PurchaseOrderCreation
from modules.procurement.order_edit_commands import PurchaseOrderEditCommand

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture(autouse=True)
async def catalog_supplier(session):
    connection = await session.connection()
    await connection.run_sync(lambda sync: PurchaseOrderCreation.__table__.create(sync, checkfirst=True))
    await connection.run_sync(lambda sync: PurchaseOrderEditCommand.__table__.create(sync, checkfirst=True))
    party = Counterparty(name="S", unp="999999993")
    session.add(party)
    await session.flush()
    session.add(Supplier(counterparty_id=party.id, name="S", unp=party.unp, status="active"))
    await session.commit()


async def _organization(api):
    books = (await api.get("/accounting/organizations")).json()
    if books:
        return books[0]["id"]
    created = await api.post("/accounting/organizations", json={"name": "Synthetic procurement company", "unp": "999999994"})
    assert created.status_code == 201, created.text
    return created.json()["id"]


async def _order_command(api, **over):
    org = await _organization(api)
    options = await api.get(f"/procurement/organizations/{org}/supplier-options?q=S")
    assert options.status_code == 200, options.text
    supplier = next(row for row in options.json()["items"] if row["name"] == "S")
    lines = over.pop("lines", [{"sku_code": "A", "qty": 10, "goods_value_byn": 1000}])
    freight = over.pop("freight_byn", 0)
    body = {"request_key": str(uuid4()), "document": {
        "supplier": supplier["name"], "supplier_id": supplier["id"], "supplier_unp": supplier["unp"],
        "eta_date": "2026-10-01", "freight_byn": f"{Decimal(str(freight)):.2f}",
        "lines": [{"sku_code": line["sku_code"], "qty": f"{Decimal(str(line['qty'])):.2f}",
                   "goods_value_byn": f"{Decimal(str(line.get('goods_value_byn', 0))):.2f}",
                   "weight": f"{Decimal(str(line.get('weight', 0))):.3f}",
                   "volume": f"{Decimal(str(line.get('volume', 0))):.4f}"} for line in lines]},
        "ownership_evidence": "Explicit synthetic lifecycle fixture", "request_basis": None}
    body["document"].update(over)
    return org, body


async def _order(api, **over):
    api.headers["X-User"] = "procurement-owner-test"
    status = over.pop("status", None)
    org, body = await _order_command(api, **over)
    api.headers["X-Expected-Organization"] = str(org)
    api.headers["X-Expected-Principal"] = "procurement-owner-test"
    r = await api.post(f"/procurement/organizations/{org}/orders", json=body)
    assert r.status_code == 201, r.text
    order_id = r.json()["order_id"]
    result = {"id": order_id, "status": "draft", "received_at": None}
    if status:
        accepted = await _edit(api, "PATCH", f"/procurement/orders/{order_id}", json={"status": status})
        assert accepted.status_code == 200, accepted.text
        result.update(status=status, received_at=accepted.json()["effect"].get("received_at"))
    return result


async def _post_command(api, **over):
    api.headers["X-User"] = "procurement-owner-test"
    org, body = await _order_command(api, **over)
    api.headers["X-Expected-Organization"] = str(org)
    api.headers["X-Expected-Principal"] = "procurement-owner-test"
    return await api.post(f"/procurement/organizations/{org}/orders", json=body)


async def _events(session, etype):
    return [e for e in (await session.execute(select(OutboxEvent))).scalars().all() if e.event_type == etype]


async def test_new_order_is_draft_not_open(api):
    """Новый заказ — draft (черновик), НЕ в открытых (sales не видит «в пути»)."""
    o = await _order(api)
    assert o["status"] == "draft"
    open_ids = {x["id"] for x in (await api.get(f"/procurement/organizations/{api.headers['X-Expected-Organization']}/open-orders")).json()["items"]}
    assert o["id"] not in open_ids


async def test_legal_transitions_emit_events(api, session):
    o = await _order(api)
    for st in ("ordered", "shipped", "customs"):
        r = await _edit(api, "PATCH",f"/procurement/orders/{o['id']}", json={"status": st})
        assert r.status_code == 200 and r.json()["effect"]["to"] == st
    changes = await _events(session, "procurement.order.status_changed")
    assert [e.payload["to"] for e in changes] == ["ordered", "shipped", "customs"]
    assert changes[0].payload["from"] == "draft"


async def test_received_sets_received_at(api):
    """P4: переход в received проставляет received_at (основа своевременности scorecard)."""
    o = await _order(api, status="ordered")
    assert o["received_at"] is None  # открытый — факта приёмки ещё нет
    received = (await _edit(api, "PATCH",f"/procurement/orders/{o['id']}", json={"status": "received"})).json()
    assert received["effect"]["received_at"] is not None


async def test_backward_transition_rejected(api):
    o = await _order(api, status="shipped")
    r = await _edit(api, "PATCH",f"/procurement/orders/{o['id']}", json={"status": "ordered"})
    assert r.status_code == 409 and r.json()["code"] == "transition_not_allowed"  # откат назад запрещён


async def test_cancel_allowed_but_not_after_received(api):
    o = await _order(api, status="ordered")
    assert (await _edit(api, "PATCH",f"/procurement/orders/{o['id']}", json={"status": "cancelled"})).status_code == 200
    o2 = await _order(api, status="received")  # создан принятым
    assert (await _edit(api, "PATCH",f"/procurement/orders/{o2['id']}", json={"status": "cancelled"})).status_code == 409


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
    await _edit(api, "PATCH",f"/procurement/orders/{o['id']}", json={"status": "received"})

    received = await _events(session, "procurement.received")
    by_sku = {e.payload["sku_code"]: e.payload for e in received}
    assert set(by_sku) == {"A", "B"}
    assert Decimal(by_sku["A"]["qty"]) == 10 and Decimal(by_sku["B"]["qty"]) == 30
    assert isinstance(by_sku["A"]["qty"], str)
    books = (await api.get("/accounting/organizations")).json()
    assert all(e.payload["organization_id"] == books[0]["id"] for e in received)
    assert all(e.payload["organization_id"] == books[0]["id"] for e in await _events(session, "procurement.landed_cost.calculated"))
    from types import SimpleNamespace

    from modules.wms.events import on_goods_received
    from modules.wms.models import ReceiptLine
    for event in received:
        await on_goods_received(event.payload, SimpleNamespace(session=session))
    await session.flush()
    receipt_lines = (await session.scalars(select(ReceiptLine))).all()
    assert {row.sku_code: row.expected_qty for row in receipt_lines} == {"A": Decimal("10"), "B": Decimal("30")}
    assert by_sku["A"]["warehouse"] == "Главный"
    assert by_sku["A"]["entity_ref"].startswith(f"purchase_order:{o['id']}:")
    assert by_sku["A"]["unit_landed_cost_byn"]  # себестоимость проставлена
    # landed cost зафиксирован (per-SKU)
    assert len((await session.execute(select(LandedCost))).scalars().all()) == 2


# ───────────────────── редактор состава (П.10) ─────────────────────


async def test_add_and_delete_line(api):
    o = await _order(api, lines=[{"sku_code": "A", "qty": 1, "goods_value_byn": 100}])
    r = await _edit(api, "POST",f"/procurement/orders/{o['id']}/lines", json={"sku_code": "B", "qty": "2.00", "goods_value_byn": "200.00"})
    assert r.status_code == 200
    assert r.json()["action"] == "add_line"
    body = (await api.get(f"/procurement/organizations/{api.headers['X-Expected-Organization']}/orders/{o['id']}")).json()
    assert {ln["sku_code"] for ln in body["lines"]} == {"A", "B"}

    line_b = next(ln for ln in body["lines"] if ln["sku_code"] == "B")
    r = await _edit(api, "DELETE",f"/procurement/orders/{o['id']}/lines/{line_b['id']}")
    assert r.status_code == 200
    assert r.json()["effect"]["line"]["id"] == line_b["id"]
    after = (await api.get(f"/procurement/organizations/{api.headers['X-Expected-Organization']}/orders/{o['id']}")).json()
    assert {ln["sku_code"] for ln in after["lines"]} == {"A"}


async def test_cannot_edit_received_order(api):
    o = await _order(api, status="received", lines=[{"sku_code": "A", "qty": 1, "goods_value_byn": 100}])
    r = await _edit(api, "POST",f"/procurement/orders/{o['id']}/lines", json={"sku_code": "B", "qty": "1.00"})
    assert r.status_code == 409  # принятый заказ не редактируется


async def test_update_header_freight_and_eta(api):
    o = await _order(
        api,
        lines=[
            {"sku_code": "A", "qty": 10, "goods_value_byn": 100, "weight": 6},
            {"sku_code": "B", "qty": 30, "goods_value_byn": 300, "weight": 14},
        ],
    )
    r = await _edit(api, "PATCH",f"/procurement/orders/{o['id']}/header", json={"freight_byn": "200.00", "eta_date": "2026-09-01"})
    assert r.status_code == 200
    saved = (await api.get(f"/procurement/organizations/{api.headers['X-Expected-Organization']}/orders/{o['id']}")).json()
    assert saved["freight_byn"] == "200.00" and saved["eta_date"] == "2026-09-01"
    # landed-preview учитывает новый фрахт (200 по весу → A unit 16.00)
    prev = (await api.get(f"/procurement/organizations/{api.headers['X-Expected-Organization']}/orders/{o['id']}/landed-preview")).json()
    by = {ln["sku_code"]: ln for ln in prev["lines"]}
    assert Decimal(by["A"]["unit_landed_cost_byn"]) == Decimal("16.0")


async def test_update_header_received_409(api):
    o = await _order(api, status="received", lines=[{"sku_code": "A", "qty": 1, "goods_value_byn": 100}])
    r = await _edit(api, "PATCH",f"/procurement/orders/{o['id']}/header", json={"freight_byn": "50.00"})
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
    prev = (await api.get(f"/procurement/organizations/{api.headers['X-Expected-Organization']}/orders/{o['id']}/landed-preview")).json()
    by = {ln["sku_code"]: ln for ln in prev["lines"]}
    # по стоимости (100/1100, 1000/1100): обе получают фрахт, LIGHT не обнулён
    assert Decimal(by["HEAVY"]["allocated_byn"]) == Decimal("27.27")
    assert Decimal(by["LIGHT"]["allocated_byn"]) == Decimal("272.73")


async def test_negative_freight_rejected(api):
    r = await _post_command(api, freight_byn=-100)
    assert r.status_code == 422  # отрицательный фрахт → невалидно


async def test_cancelled_order_not_editable(api):
    o = await _order(api, status="ordered", lines=[{"sku_code": "A", "qty": 1, "goods_value_byn": 100}])
    await _edit(api, "PATCH",f"/procurement/orders/{o['id']}", json={"status": "cancelled"})
    r = await _edit(api, "POST",f"/procurement/orders/{o['id']}/lines", json={"sku_code": "B", "qty": "1.00"})
    assert r.status_code == 409  # отменённый заказ — терминальный, не редактируется


async def test_cannot_create_cancelled(api):
    r = await _post_command(api, status="cancelled")
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
    prev = (await api.get(f"/procurement/organizations/{api.headers['X-Expected-Organization']}/orders/{o['id']}/landed-preview")).json()
    by_sku = {ln["sku_code"]: ln for ln in prev["lines"]}
    # фрахт 200 по весу → A: landed 160 unit 16.00; B: landed 440 unit 14.67
    assert Decimal(by_sku["A"]["unit_landed_cost_byn"]) == Decimal("16.0")
    assert Decimal(by_sku["B"]["unit_landed_cost_byn"]) == Decimal("14.67")
    assert Decimal(prev["total_landed_byn"]) == Decimal("600.0")
    # фиксации НЕ было
    assert (await session.execute(select(LandedCost))).scalars().all() == []

async def test_create_received_order_cannot_bypass_organization_decision(api, session):
    response = await _post_command(api, status="received")
    assert response.status_code == 422
    assert await _events(session, "procurement.received") == []
    assert (await session.scalars(select(PurchaseOrder))).all() == []
    assert (await api.get("/procurement/orders")).status_code == 410

async def test_request_receipt_event_uses_confirmed_organization(api, session):
    await _order(api)
    books = (await api.get("/accounting/organizations")).json()
    request = await api.post("/procurement/requests", json={"supplier": "S", "item": "A", "qty": 2, "amount": 10})
    assert request.status_code == 201, request.text
    assigned = await api.post(f"/procurement/organizations/{books[0]['id']}/purchase-ownership", json={"kind": "request", "source_id": request.json()["id"], "evidence": "Explicit synthetic request owner"})
    assert assigned.status_code == 201, assigned.text
    api.headers["X-Expected-Organization"] = str(books[0]["id"])
    api.headers["X-Expected-Principal"] = "procurement-owner-test"
    response = await api.patch(f"/procurement/requests/{request.json()['id']}", json={"stage": "qc", "organization_id": 999999})
    assert response.status_code == 200, response.text
    events = await _events(session, "procurement.received")
    assert len(events) == 1
    assert events[0].payload["organization_id"] == books[0]["id"]


async def _edit(client, method, path, json=None):
    import re
    from uuid import uuid4
    match = re.fullmatch(r"/procurement/orders/(\d+)(.*)", path)
    order_id, suffix = int(match[1]), match[2]
    action = "delete_line" if method == "DELETE" else {"/lines": "add_line", "/header": "header", "/plan": "plan", "": "status"}[suffix]
    payload = {"line_id": int(suffix.rsplit("/", 1)[1])} if action == "delete_line" else json
    org = getattr(client, "command_org", client.headers["X-Expected-Organization"])
    return await client.post(f"/procurement/organizations/{org}/orders/{order_id}/edit-commands", json={
        "version": 1, "request_key": str(uuid4()), "order_id": order_id, "action": action, "payload": payload})

async def test_received_command_exact_replay_emits_nothing_twice(api, session):
    from uuid import uuid4

    order = await _order(api, lines=[{"sku_code": "A", "qty": 2, "goods_value_byn": 20}])
    org = api.headers["X-Expected-Organization"]
    path = f"/procurement/organizations/{org}/orders/{order['id']}/edit-commands"
    body = {"version": 1, "request_key": str(uuid4()), "order_id": order["id"], "action": "status", "payload": {"status": "received"}}
    first = await api.post(path, json=body)
    assert first.status_code == 200, first.text
    event_ids = [e.id for e in (await session.scalars(select(OutboxEvent))).all()]
    landed_ids = [x.id for x in (await session.scalars(select(LandedCost))).all()]
    assert first.json()["effect"]["event_ids"] == event_ids
    assert len(event_ids) >= 3 and landed_ids
    for target in [path, path + "/reconcile"]:
        again = await api.post(target, json=body)
        assert again.content == first.content
        assert [e.id for e in (await session.scalars(select(OutboxEvent))).all()] == event_ids
        assert [x.id for x in (await session.scalars(select(LandedCost))).all()] == landed_ids
