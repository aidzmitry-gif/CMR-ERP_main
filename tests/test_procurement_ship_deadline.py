"""Legacy deadline event subscription plus current company-owned customer planning.

Producer/event synchronization remains covered unchanged. Planning consumes only
explicit outstanding reservations of the selected company, reviews live customer
terms and saves a deliberately chosen date through the durable command protocol.
A matching SKU or historical signal alone cannot authorize an order relationship.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from core.domain.models import OutboxEvent
from core.runtime.app import create_app
from core.runtime.deps import get_session
from core.services.eventbus import EventContext
from modules.procurement import customer_deadlines
from modules.procurement.models import PurchaseOrder, ShipRequirement
from modules.procurement.order_edit_commands import PurchaseOrderEditCommand
from modules.sales.accounting_ownership import DealOwnership
from modules.sales.models import Deal
from modules.wms.models import StockMovement
from tests import test_procurement_customer_deadline_risk as deadline_risk
from tests.accounting.test_expected_reservations import payload as expected_payload

pytestmark = pytest.mark.asyncio
owned_deadline_order = deadline_risk.risk_order


@pytest_asyncio.fixture
async def deadline_app(session):
    app = create_app()

    async def _override():
        yield session

    app.dependency_overrides[get_session] = _override
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", headers={"X-User-Roles": "director"}
    ) as client:
        yield client, app.state.core


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




async def _owned_review(client, context):
    response = await client.get(context["url"])
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["complete_customer_demand"] is False
    return body


async def _owned_plan(client, context, *, target=None, method="container", expected=200):
    payload = {"transport_method_code": method}
    if target is not None:
        payload["target_arrival_date"] = target
    command = {"version": 1, "request_key": str(uuid4()), "order_id": context["order"],
               "action": "plan", "payload": payload}
    response = await client.post(f"{context['prefix']}/orders/{context['order']}/edit-commands", json=command,
        headers={"X-Expected-Organization": str(context["org"]), "X-Expected-Principal": "deadline-review-owner"})
    assert response.status_code == expected, response.text
    return response


async def _linked_customer(client, session, context, number, deadline, *, rate=None):
    deal = Deal(number=number, title="Synthetic linked customer", counterparty="Synthetic buyer", amount=0,
                ship_deadline=deadline, penalty_rate_pct=Decimal(rate) if rate is not None else None)
    session.add(deal)
    await session.flush()
    session.add(DealOwnership(deal_id=deal.id, organization_id=context["org"], snapshot={},
                             evidence="Synthetic explicit customer ownership", actor="deadline-review-owner"))
    await session.commit()
    response = await client.post(f"{context['prefix']}/expected-reservations",
        json=expected_payload(context["order"], context["line"], deal.id, "20.00"))
    assert response.status_code == 201, response.text


async def _no_physical_writes(session):
    assert await session.scalar(select(StockMovement.id)) is None
    assert await session.scalar(select(OutboxEvent.id)) is None


# ───────────────────────── подписка на срок клиента ─────────────────────────


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


# ───────────────────────── обратное планирование от срока + риск ─────────────────────────




async def test_plan_auto_derives_target_from_deadline(api, session, owned_deadline_order):
    """Review suggests earliest customer date minus three; saving is explicit."""
    context = owned_deadline_order
    review = await _owned_review(api, context)
    assert review["risk_details"]["required_by"] == "2026-12-31"
    assert review["earliest_required_arrival"] == "2026-12-28"
    order = await session.get(PurchaseOrder, context["order"], populate_existing=True)
    assert order.target_arrival_date is None  # reading the hint cannot save it
    saved = await _owned_plan(api, context, target=review["earliest_required_arrival"])
    assert saved.json()["effect"]["target_arrival_date"] == "2026-12-28"
    plan = await _owned_review(api, context)
    assert plan["risk_details"]["target_arrival_date"] == "2026-12-28"
    assert plan["at_risk"] is False and plan["risk_details"]["slack_days"] == 0
    await _no_physical_writes(session)


async def test_plan_flags_risk_and_penalty_when_late(api, session, owned_deadline_order):
    """The exact linked customer's late arrival keeps its current penalty terms."""
    context = owned_deadline_order
    deal = await session.get(Deal, context["deal"])
    deal.number, deal.ship_deadline = "СД-2", "2026-07-05"
    deal.penalty_rate_pct = Decimal("1.00")
    await session.commit()
    await _owned_plan(api, context, target="2026-10-01", method="truck")
    plan = await _owned_review(api, context)
    assert plan["earliest_required_arrival"] == "2026-07-02"
    assert plan["at_risk"] is True and len(plan["risk_details"]["items"]) == 1
    item = plan["risk_details"]["items"][0]
    assert item["number"] == "СД-2" and item["penalty_rate_pct"] == "1.00"
    assert item["penalty_cap_pct"] == "10.00" and item["slack_days"] < 0
    await _no_physical_writes(session)


async def test_plan_no_target_no_deadline_422(api, session, owned_deadline_order):
    """No customer date remains unknown; an explicit-date command cannot omit its date."""
    context = owned_deadline_order
    deal = await session.get(Deal, context["deal"])
    deal.ship_deadline = None
    await session.commit()
    review = await _owned_review(api, context)
    assert review["earliest_required_arrival"] is None and review["unresolved_deadlines"] == 1
    assert review["at_risk"] is None
    await _owned_plan(api, context, expected=422)
    order = await session.get(PurchaseOrder, context["order"], populate_existing=True)
    assert order.target_arrival_date is None
    assert await session.scalar(select(PurchaseOrderEditCommand.id)) is None
    await _no_physical_writes(session)


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


async def test_unplanned_machine_with_deadline_is_at_risk(api, session, owned_deadline_order):
    """An explicitly linked demand with no saved arrival must not appear safe."""
    plan = await _owned_review(api, owned_deadline_order)
    assert plan["risk_details"]["target_arrival_date"] is None
    assert plan["earliest_required_arrival"] == "2026-12-28"
    assert plan["at_risk"] is True
    assert await session.scalar(select(PurchaseOrderEditCommand.id)) is None
    await _no_physical_writes(session)


async def test_plan_multi_deal_earliest_deadline_wins(api, session, owned_deadline_order):
    """Two actual reservations on the order: earliest wins, only the late row is late."""
    context = owned_deadline_order
    deal = await session.get(Deal, context["deal"])
    deal.number, deal.ship_deadline = "СД-1", "2027-06-01"
    await session.commit()
    await _linked_customer(api, session, context, "СД-2", "2026-11-20", rate="1.00")
    await _owned_plan(api, context, target="2027-01-01", method="truck")
    plan = await _owned_review(api, context)
    assert plan["risk_details"]["required_by"] == "2026-11-20"
    assert plan["earliest_required_arrival"] == "2026-11-17"
    items = plan["risk_details"]["items"]
    assert {i["number"] for i in items} == {"СД-1", "СД-2"}
    assert {i["number"] for i in items if i["slack_days"] < 0} == {"СД-2"}
    assert next(i for i in items if i["number"] == "СД-2")["penalty_rate_pct"] == "1.00"
    assert plan["at_risk"] is True
    await _no_physical_writes(session)


async def test_unparsed_deadline_ignored_in_plan(api, session, owned_deadline_order):
    """An unparsed date cannot drive the plan and remains visibly unresolved."""
    context = owned_deadline_order
    deal = await session.get(Deal, context["deal"])
    deal.number, deal.ship_deadline = "СД-J", "24 июля 2026"
    await session.commit()
    first = await _owned_review(api, context)
    assert first["earliest_required_arrival"] is None and first["at_risk"] is None
    assert first["unresolved_deadlines"] == 1
    await _owned_plan(api, context, expected=422)
    await _linked_customer(api, session, context, "СД-OK", "2026-12-31")
    await _owned_plan(api, context, target="2027-06-01")
    plan = await _owned_review(api, context)
    assert plan["risk_details"]["required_by"] == "2026-12-31"
    assert plan["earliest_required_arrival"] == "2026-12-28"
    assert plan["unresolved_deadlines"] == 1 and plan["at_risk"] is True
    items = plan["risk_details"]["items"]
    assert next(i for i in items if i["number"] == "СД-J")["slack_days"] is None
    assert {i["number"] for i in items if i["slack_days"] is not None and i["slack_days"] < 0} == {"СД-OK"}
    await _no_physical_writes(session)


async def test_past_start_is_at_risk(api, session, owned_deadline_order, monkeypatch):
    """Past collection start is risky even when the customer's arrival still has slack."""
    class MidyearClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 6, 28, tzinfo=tz)

    monkeypatch.setattr(customer_deadlines, "datetime", MidyearClock)
    saved = await _owned_plan(api, owned_deadline_order, target="2026-08-01")
    assert saved.json()["effect"]["start_date"] < "2026-06-28"
    plan = await _owned_review(api, owned_deadline_order)
    assert plan["risk_details"]["schedule_start_date"] == saved.json()["effect"]["start_date"]
    assert plan["risk_details"]["slack_days"] > 0
    assert plan["risk_details"]["schedule_start_in_past"] is True and plan["at_risk"] is True
    await _no_physical_writes(session)


async def test_slack_days_exact_both_sides(api, session, owned_deadline_order):
    """The same linked December28 requirement gives exact +5 and -4 day slack."""
    await _owned_plan(api, owned_deadline_order, target="2026-12-23", method="truck")
    early = await _owned_review(api, owned_deadline_order)
    assert early["risk_details"]["slack_days"] == 5 and early["at_risk"] is False
    await _owned_plan(api, owned_deadline_order, target="2027-01-01", method="truck")
    late = await _owned_review(api, owned_deadline_order)
    assert late["risk_details"]["slack_days"] == -4 and late["at_risk"] is True
    await _no_physical_writes(session)
