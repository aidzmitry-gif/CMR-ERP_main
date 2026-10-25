"""Legacy deadline-event compatibility and live, explicitly linked customer planning.

A plan date is written only by an explicit edit after reviewing current linked
reservations. The legacy global-SKU requirement cache is not a planning source.
"""
from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select

from core.domain.models import Counterparty, Sku
from core.services.eventbus import EventContext
from modules.procurement import routes as procurement_routes
from modules.procurement import scoped_reads
from modules.procurement.deal_demands import DealProcurementDemand  # noqa: F401
from modules.procurement.models import PurchaseOrderLine, ShipRequirement, Supplier
from modules.procurement.order_creation import PurchaseOrderCreation  # noqa: F401
from modules.procurement.order_edit_commands import PurchaseOrderEditCommand  # noqa: F401

pytestmark = pytest.mark.asyncio


class PlanningClock(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 1, 1, tzinfo=tz)


@pytest_asyncio.fixture
async def deadline_app(api, session, monkeypatch):
    monkeypatch.setattr(procurement_routes, "datetime", PlanningClock)
    monkeypatch.setattr(scoped_reads, "datetime", PlanningClock)
    api.headers["X-User"] = "deadline-owner"
    party = Counterparty(name="S", unp="999999991")
    buyer = Counterparty(name="Synthetic deadline buyer", unp="999999992")
    session.add_all([party, buyer, Sku(code="A", title="Synthetic A", unit="шт"),
                     Sku(code="B", title="Synthetic B", unit="шт")])
    await session.flush()
    supplier = Supplier(counterparty_id=party.id, name=party.name, unp=party.unp, status="active")
    session.add(supplier)
    await session.commit()
    created = await api.post("/accounting/organizations", json={
        "name": "Synthetic deadline company", "unp": "999999994"})
    assert created.status_code == 201, created.text
    api.headers["X-Expected-Organization"] = str(created.json()["id"])
    api.headers["X-Expected-Principal"] = "deadline-owner"
    api.deadline_supplier_id, api.deadline_buyer_id = supplier.id, buyer.id
    yield api, api._transport.app.state.core


async def _command(client, order, action, payload):
    org = client.headers["X-Expected-Organization"]
    return await client.post(f"/procurement/organizations/{org}/orders/{order['id']}/edit-commands",
        json={"version": 1, "request_key": str(uuid4()), "order_id": order["id"],
              "action": action, "payload": payload})


async def _order(client, session, *, sku="A", qty="5.00", value="500.00"):
    org = client.headers["X-Expected-Organization"]
    created = await client.post(f"/procurement/organizations/{org}/orders", json={
        "request_key": str(uuid4()), "document": {"supplier": "S",
            "supplier_id": client.deadline_supplier_id, "supplier_unp": "999999991",
            "eta_date": None, "freight_byn": "0.00", "lines": [{"sku_code": sku,
                "qty": qty, "goods_value_byn": value, "weight": "0.000", "volume": "0.0000"}]},
        "ownership_evidence": "Synthetic order for confirmed client demand", "request_basis": None})
    assert created.status_code == 201, created.text
    order_id = created.json()["order_id"]
    line = await session.scalar(select(PurchaseOrderLine).where(
        PurchaseOrderLine.order_id == order_id, PurchaseOrderLine.sku_code == sku))
    order = {"id": order_id, "line_id": line.id, "sku_code": sku}
    status = await _command(client, order, "status", {"status": "ordered"})
    assert status.status_code == 200 and status.json()["outcome"] == "applied", status.text
    return order


async def _linked(client, session, order, deadline, *, number="SD-1", rate=None, cap=None, terms=None, allocate=True):
    org = client.headers["X-Expected-Organization"]
    response = await client.post("/sales/deals", json={"number": number,
        "title": "Synthetic deadline deal", "counterparty": "Synthetic deadline buyer",
        "counterparty_id": client.deadline_buyer_id, "ship_deadline": deadline,
        "penalty_rate_pct": rate, "penalty_cap_pct": cap, "penalty_terms": terms})
    assert response.status_code == 201, response.text
    deal = response.json()
    prefix = f"/sales/organizations/{org}/deals/{deal['id']}"
    preview = await client.get(prefix + "/ownership-preview")
    assert preview.status_code == 200, preview.text
    claimed = await client.post(prefix + "/ownership", json={
        "expected_snapshot": preview.json()["snapshot"], "evidence": "Synthetic explicit deal organization"})
    assert claimed.status_code == 201, claimed.text
    sku_id = await session.scalar(select(Sku.id).where(Sku.code == order["sku_code"]))
    item = await client.post(f"/sales/deals/{deal['id']}/items", json={"sku_id": sku_id, "qty": "1.00"})
    assert item.status_code == 201, item.text
    demand = await client.post(f"/procurement/organizations/{org}/deals/{deal['id']}/demands", json={
        "deal_item_id": item.json()["id"], "qty": "1.00", "request_key": str(uuid4()),
        "evidence": "Synthetic confirmed customer demand"})
    assert demand.status_code == 201, demand.text
    if allocate:
        linked = await client.post(f"/procurement/organizations/{org}/demands/{demand.json()['id']}/allocations", json={
            "order_id": order["id"], "order_line_id": order["line_id"], "qty": "1.00",
            "request_key": str(uuid4()), "evidence": "Synthetic exact supplier line allocation"})
        assert linked.status_code == 201, linked.text
    return deal


async def _review(client, order):
    org = client.headers["X-Expected-Organization"]
    response = await client.get(f"/procurement/organizations/{org}/orders/{order['id']}/customer-deadlines")
    assert response.status_code == 200, response.text
    assert response.json()["complete_customer_demand"] is False
    return response.json()


async def _plan(client, order, target, method="truck"):
    response = await _command(client, order, "plan", {
        "transport_method_code": method, "target_arrival_date": target})
    assert response.status_code == 200 and response.json()["outcome"] == "applied", response.text
    return response.json()["effect"]


async def _read_plan(client, order):
    org = client.headers["X-Expected-Organization"]
    response = await client.get(f"/procurement/organizations/{org}/orders/{order['id']}/plan")
    assert response.status_code == 200, response.text
    return response.json()


async def _emit_deadline(core, session, **over):
    payload = {
        "deal_id": 1, "number": "СД-1", "counterparty": "ООО Клиент",
        "ship_deadline": "2026-12-31", "penalty_rate_pct": 0.5, "penalty_cap_pct": 10.0,
        "penalty_terms": "0.5%/день, до 10%", "items": [{"sku_code": "A", "qty": 5}],
        "actor": "sales", "entity_ref": "deal:1",
    }
    payload.update(over)
    core.event_bus.emit(session, "sales.deal.ship_deadline.set", payload)
    await core.event_bus.relay_once(session, EventContext(session, core.services))



async def _reqs(session):
    return (await session.execute(select(ShipRequirement))).scalars().all()



async def test_subscription_registered(deadline_app):
    _, core = deadline_app
    handlers = core.event_bus._handlers.get("sales.deal.ship_deadline.set", [])
    assert any(h.__name__ == "on_ship_deadline_set" for h in handlers)



async def test_deadline_event_stores_requirement(deadline_app, session):
    client, core = deadline_app
    await _emit_deadline(core, session)
    rows = await _reqs(session)
    assert len(rows) == 1
    r = rows[0]
    assert r.deal_id == 1 and r.sku_code == "A"
    assert r.ship_deadline == "2026-12-31"
    assert str(r.ship_deadline_date) == "2026-12-31"  # разобрана в дату
    assert float(r.penalty_rate_pct) == 0.5



async def test_deadline_event_idempotent_and_syncs_items(deadline_app, session):
    client, core = deadline_app
    await _emit_deadline(core, session, items=[{"sku_code": "A", "qty": 5}, {"sku_code": "B", "qty": 2}])
    assert {r.sku_code for r in await _reqs(session)} == {"A", "B"}
    # повтор с другим сроком + убрана позиция B → A обновлена, B снята (не дубль)
    await _emit_deadline(core, session, ship_deadline="2026-11-30", items=[{"sku_code": "A", "qty": 9}])
    rows = await _reqs(session)
    assert {r.sku_code for r in rows} == {"A"}  # B снята
    assert rows[0].ship_deadline == "2026-11-30" and float(rows[0].qty) == 9  # A обновлена



async def test_deadline_event_without_deal_id_skipped(deadline_app, session):
    client, core = deadline_app
    await _emit_deadline(core, session, deal_id=None)
    assert await _reqs(session) == []



async def test_deadline_event_duplicate_sku_no_crash(deadline_app, session):
    """Дубль sku в позициях сделки → одна строка (UNIQUE не падает, relay не зависает) — last-write-wins."""
    client, core = deadline_app
    await _emit_deadline(core, session, items=[{"sku_code": "A", "qty": 3}, {"sku_code": "A", "qty": 5}])
    rows = [r for r in await _reqs(session) if r.sku_code == "A"]
    assert len(rows) == 1 and float(rows[0].qty) == 5



async def test_deadline_empty_items_preserves_requirements(deadline_app, session):
    """Сигнал с пустыми позициями НЕ стирает уже сохранённые требования сделки (защита от стирания)."""
    client, core = deadline_app
    await _emit_deadline(core, session, items=[{"sku_code": "A", "qty": 3}, {"sku_code": "B", "qty": 1}])
    assert len(await _reqs(session)) == 2
    await _emit_deadline(core, session, items=[])  # пустой сигнал
    assert len(await _reqs(session)) == 2  # ничего не стёрто



async def test_reviewed_deadline_explicitly_sets_plan_target(deadline_app, session):
    client, _ = deadline_app
    order = await _order(client, session)
    await _linked(client, session, order, "2026-12-31")
    reviewed = await _review(client, order)
    assert reviewed["earliest_required_arrival"] == "2026-12-28"
    assert reviewed["at_risk"] is True and reviewed["slack_days"] is None
    plan = await _plan(client, order, reviewed["earliest_required_arrival"], "container")
    assert plan["target_arrival_date"] == "2026-12-28" and plan["total_days"] == 112
    assert plan["schedule_start_in_past"] is False
    assert (await _read_plan(client, order))["target_arrival_date"] == "2026-12-28"
    reviewed = await _review(client, order)
    assert reviewed["at_risk"] is False and reviewed["slack_days"] == 0
    assert reviewed["items"][0]["ship_deadline"] == "2026-12-31"


async def test_plan_flags_risk_and_penalty_when_late(deadline_app, session):
    client, _ = deadline_app
    order = await _order(client, session, sku="B", qty="1.00", value="100.00")
    deal = await _linked(client, session, order, "2026-07-05", number="SD-2",
                         rate="1.00", cap="10.00", terms="1% по условиям договора")
    await _plan(client, order, "2026-10-01")
    result = await _review(client, order)
    assert result["earliest_required_arrival"] == "2026-07-02" and result["at_risk"] is True
    assert len(result["items"]) == 1
    item = result["items"][0]
    assert item["deal_id"] == deal["id"] and item["deal_number"] == "SD-2"
    assert item["penalty_rate_pct"] == "1.00" and item["penalty_cap_pct"] == "10.00"
    assert item["penalty_terms"] == "1% по условиям договора" and item["slack_days"] < 0


async def test_plan_no_target_no_deadline_422(deadline_app, session):
    client, _ = deadline_app
    order = await _order(client, session)
    response = await _command(client, order, "plan", {"transport_method_code": "container"})
    assert response.status_code == 422, response.text
    assert (await _read_plan(client, order))["target_arrival_date"] is None
    result = await _review(client, order)
    assert result["items"] == [] and result["at_risk"] is None and result["slack_days"] is None


async def test_unplanned_machine_with_deadline_is_at_risk(deadline_app, session):
    client, _ = deadline_app
    order = await _order(client, session)
    await _linked(client, session, order, "2026-12-31")
    assert (await _read_plan(client, order))["target_arrival_date"] is None
    result = await _review(client, order)
    assert result["earliest_required_arrival"] == "2026-12-28"
    assert result["at_risk"] is True and result["slack_days"] is None


async def test_plan_multi_deal_earliest_deadline_wins(deadline_app, session):
    client, _ = deadline_app
    order = await _order(client, session)
    first = await _linked(client, session, order, "2027-06-01", number="SD-1", rate="0.00")
    second = await _linked(client, session, order, "2026-11-20", number="SD-2", rate="1.00")
    unrelated = await _linked(client, session, order, "2026-01-01", number="UNLINKED", allocate=False)
    await _plan(client, order, "2027-01-01")
    result = await _review(client, order)
    assert result["earliest_required_arrival"] == "2026-11-17"
    assert {x["deal_id"] for x in result["items"]} == {first["id"], second["id"]}
    assert unrelated["id"] not in {x["deal_id"] for x in result["items"]}
    assert {x["deal_number"] for x in result["items"] if x["at_risk"]} == {"SD-2"}
    zero = next(x for x in result["items"] if x["deal_id"] == first["id"])
    assert zero["penalty_rate_pct"] == "0.00" and zero["penalty_cap_pct"] is None


async def test_unparsed_deadline_stays_unknown_in_review(deadline_app, session):
    client, _ = deadline_app
    order = await _order(client, session)
    unknown = await _linked(client, session, order, "24 июля 2026", number="SD-JUNK")
    result = await _review(client, order)
    assert result["earliest_required_arrival"] is None and result["at_risk"] is None
    assert result["unresolved_deadlines"] == 1 and result["slack_days"] is None
    await _linked(client, session, order, "2026-12-31", number="SD-OK")
    await _plan(client, order, "2027-06-01")
    result = await _review(client, order)
    assert result["earliest_required_arrival"] == "2026-12-28" and result["unresolved_deadlines"] == 1
    item = next(x for x in result["items"] if x["deal_id"] == unknown["id"])
    assert item["deadline_status"] == "missing_or_unparsed" and item["at_risk"] is None
    assert item["required_arrival"] is None and item["slack_days"] is None
    assert item["penalty_rate_pct"] is None and item["penalty_cap_pct"] is None


async def test_past_start_is_at_risk(deadline_app, session):
    client, _ = deadline_app
    order = await _order(client, session)
    plan = await _plan(client, order, "2026-01-02", "container")
    assert plan["start_date"] < "2026-01-01" and plan["total_days"] == 112
    assert plan["schedule_start_in_past"] is True
    assert plan["at_risk"] is None and plan["customer_requirements_status"] == "unverified"


async def test_slack_days_exact_both_sides(deadline_app, session):
    client, _ = deadline_app
    order = await _order(client, session)
    await _linked(client, session, order, "2026-12-31")
    await _plan(client, order, "2026-12-23")
    early = await _review(client, order)
    assert early["slack_days"] == 5 and early["at_risk"] is False
    assert early["items"][0]["slack_days"] == 5
    await _plan(client, order, "2027-01-01")
    late = await _review(client, order)
    assert late["slack_days"] == -4 and late["at_risk"] is True
    assert late["items"][0]["slack_days"] == -4
