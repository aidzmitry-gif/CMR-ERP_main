"""Current linked customer requirements, plan risk and immutable command replay."""
from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select

from core.domain.models import OutboxEvent, Sku
from modules.procurement import customer_deadlines
from modules.procurement.expected_reservations import ExpectedReservationEvent
from modules.procurement.models import PurchaseOrder, PurchaseOrderMilestone
from modules.procurement.order_edit_commands import PurchaseOrderEditCommand
from modules.sales.accounting_ownership import DealOwnership
from modules.sales.models import Deal, DealItem
from modules.wms.models import StockMovement
from tests.accounting.test_expected_reservations import payload, setup_expected


@pytest_asyncio.fixture
async def risk_order(api, session, monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 1, 1, tzinfo=tz)

    monkeypatch.setattr(customer_deadlines, "datetime", Clock, raising=False)
    api.headers["X-User"] = "deadline-review-owner"
    organization = await api.post("/accounting/organizations", json={
        "name": "Synthetic deadline company", "unp": "999999976",
    })
    assert organization.status_code == 201, organization.text
    org = organization.json()["id"]
    order_id, line_id, deal_id = await setup_expected(session, [org])
    deal = await session.get(Deal, deal_id)
    deal.ship_deadline = "2026-12-31"
    deal.penalty_rate_pct = Decimal("1.00")
    deal.penalty_cap_pct = Decimal("10.00")
    deal.penalty_terms = "Synthetic contract: 1% per day, capped at 10%"
    await session.commit()
    prefix = f"/procurement/organizations/{org}"
    created = await api.post(f"{prefix}/expected-reservations", json=payload(order_id, line_id, deal_id))
    assert created.status_code == 201, created.text
    return {"org": org, "order": order_id, "line": line_id, "deal": deal_id,
            "reservation": created.json()["reservations"][0]["id"],
            "prefix": prefix, "url": f"{prefix}/orders/{order_id}/customer-deadlines"}


@pytest.mark.parametrize("target,slack,risk", [
    (date(2026, 12, 23), 5, False), (date(2027, 1, 1), -4, True), (None, None, True),
])
async def test_owned_deadline_slack_and_current_penalty(api, session, risk_order, target, slack, risk):
    order = await session.get(PurchaseOrder, risk_order["order"])
    order.target_arrival_date = target
    await session.commit()
    response = await api.get(risk_order["url"])
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["earliest_required_arrival"] == "2026-12-28"
    assert body["at_risk"] is risk and body["complete_customer_demand"] is False
    details = body["risk_details"]
    assert details["version"] == 1 and details["required_by"] == "2026-12-31"
    assert details["slack_days"] == slack
    assert details["target_arrival_date"] == (target.isoformat() if target else None)
    assert details["schedule_start_in_past"] is None
    row = details["items"][0]
    assert row["reservation_id"] == risk_order["reservation"] and row["number"] == "DEAL-EXPECTED"
    assert row["slack_days"] == slack
    assert row["penalty_rate_pct"] == "1.00" and row["penalty_cap_pct"] == "10.00"
    assert row["penalty_terms"] == "Synthetic contract: 1% per day, capped at 10%"
    assert await session.scalar(select(StockMovement.id)) is None
    assert await session.scalar(select(OutboxEvent.id)) is None


async def test_earliest_deadline_uses_only_outstanding_explicit_company_links(api, session, risk_order):
    early = Deal(number="EARLY-LINKED", title="Early customer", counterparty="Earlier buyer", amount=0,
                 ship_deadline="2026-12-20")
    foreign = Deal(number="FOREIGN-UNLINKED", title="Foreign customer", counterparty="Foreign buyer", amount=0,
                   ship_deadline="2026-01-02", penalty_terms="Must never appear")
    unlinked = Deal(number="OWN-UNLINKED", title="Unlinked own customer", counterparty="Other buyer", amount=0,
                    ship_deadline="2026-01-03", penalty_terms="Unlinked terms must never appear")
    sku = Sku(code="SKU-EXPECTED", title="Synthetic same SKU", unit="шт")
    session.add_all([early, foreign, unlinked, sku])
    await session.flush()
    session.add_all([
        DealOwnership(deal_id=early.id, organization_id=risk_order["org"], snapshot={},
                      evidence="Synthetic explicit client ownership", actor="deadline-review-owner"),
        DealOwnership(deal_id=unlinked.id, organization_id=risk_order["org"], snapshot={},
                      evidence="Owned deal without supplier reservation", actor="deadline-review-owner"),
        DealItem(deal_id=foreign.id, sku_id=sku.id, qty=Decimal("5")),
        DealItem(deal_id=unlinked.id, sku_id=sku.id, qty=Decimal("5")),
    ])
    await session.commit()
    created = await api.post(f"{risk_order['prefix']}/expected-reservations",
                             json=payload(risk_order["order"], risk_order["line"], early.id, "20.00"))
    assert created.status_code == 201, created.text
    body = (await api.get(risk_order["url"])).json()
    assert body["earliest_required_arrival"] == "2026-12-17"
    assert {r["number"] for r in body["risk_details"]["items"]} == {"EARLY-LINKED", "DEAL-EXPECTED"}
    assert "Must never appear" not in str(body)
    assert "Unlinked terms must never appear" not in str(body)
    reservation = next(row["reservation_id"] for row in body["items"] if row["deal_id"] == early.id)
    released = await api.post(f"{risk_order['prefix']}/expected-reservations/{reservation}/events", json={
        "kind": "release", "qty": "20.00", "request_key": str(uuid4()), "evidence": "Customer released demand",
    })
    assert released.status_code == 201, released.text
    body = (await api.get(risk_order["url"])).json()
    assert body["earliest_required_arrival"] == "2026-12-28"
    assert [r["number"] for r in body["risk_details"]["items"]] == ["DEAL-EXPECTED"]


async def test_past_schedule_start_is_risk_even_with_positive_customer_slack(api, session, risk_order):
    order = await session.get(PurchaseOrder, risk_order["order"])
    order.target_arrival_date = date(2026, 12, 23)
    session.add(PurchaseOrderMilestone(order_id=order.id, stage="collection", seq=0,
        duration_days=28, planned_date=date(2026, 1, 20)))
    await session.commit()
    body = (await api.get(risk_order["url"])).json()
    assert body["risk_details"]["slack_days"] == 5
    assert body["risk_details"]["schedule_start_date"] == "2025-12-23"
    assert body["risk_details"]["schedule_start_in_past"] is True
    assert body["at_risk"] is True


async def test_unrepresentable_arrival_remains_unknown_without_server_error(api, session, risk_order):
    deal = await session.get(Deal, risk_order["deal"])
    deal.ship_deadline = "0001-01-01"
    await session.commit()
    response = await api.get(risk_order["url"])
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["earliest_required_arrival"] is None and body["unresolved_deadlines"] == 1
    assert body["at_risk"] is None and body["risk_details"]["slack_days"] is None
    assert body["items"][0]["deadline_status"] == "unrepresentable_arrival"


async def test_live_deadline_refresh_cannot_rewrite_saved_plan_replay(api, session, risk_order):
    review = (await api.get(risk_order["url"])).json()
    command = {"version": 1, "request_key": str(uuid4()), "order_id": risk_order["order"], "action": "plan",
               "payload": {"transport_method_code": "truck", "target_arrival_date": review["earliest_required_arrival"]}}
    headers = {"X-Expected-Organization": str(risk_order["org"]), "X-Expected-Principal": "deadline-review-owner"}
    url = f"{risk_order['prefix']}/orders/{risk_order['order']}/edit-commands"
    first = await api.post(url, json=command, headers=headers)
    assert first.status_code == 200, first.text
    assert first.json()["effect"]["target_arrival_date"] == "2026-12-28"
    deal = await session.get(Deal, risk_order["deal"])
    deal.ship_deadline = "2026-12-20"
    deal.penalty_rate_pct = Decimal("2.00")
    await session.commit()
    latest = (await api.get(risk_order["url"])).json()
    assert latest["earliest_required_arrival"] == "2026-12-17" and latest["at_risk"] is True
    assert latest["risk_details"]["items"][0]["penalty_rate_pct"] == "2.00"
    for suffix in ("", "/reconcile"):
        repeated = await api.post(url + suffix, json=command, headers=headers)
        assert repeated.status_code == 200 and repeated.content == first.content
    assert len((await session.scalars(select(PurchaseOrderEditCommand.id))).all()) == 1
    assert await session.scalar(select(StockMovement.id)) is None
    assert await session.scalar(select(OutboxEvent.id)) is None


async def test_unknown_deadline_and_penalty_are_distinct_from_explicit_zero(api, session, risk_order):
    deal = await session.get(Deal, risk_order["deal"])
    deal.ship_deadline = "по согласованию"
    deal.penalty_rate_pct = None
    deal.penalty_cap_pct = Decimal("0.00")
    deal.penalty_terms = None
    await session.commit()
    body = (await api.get(risk_order["url"])).json()
    details = body["risk_details"]
    assert body["unresolved_deadlines"] == 1 and body["at_risk"] is None
    assert details["required_by"] is None and details["slack_days"] is None
    assert details["items"][0]["penalty_rate_pct"] is None
    assert details["items"][0]["penalty_cap_pct"] == "0.00"
    assert details["items"][0]["penalty_terms"] is None
    # Releasing the only outstanding obligation must not invent a zero risk.
    session.add(ExpectedReservationEvent(organization_id=risk_order["org"], reservation_id=risk_order["reservation"],
        kind="release", qty=Decimal("60"), request_key=str(uuid4()), evidence="Synthetic full release", actor="deadline-review-owner"))
    await session.commit()
    empty = (await api.get(risk_order["url"])).json()
    assert empty["items"] == [] and empty["risk_details"]["items"] == [] and empty["at_risk"] is None
