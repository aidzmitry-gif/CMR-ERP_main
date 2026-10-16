"""RFQ belongs to an explicitly owned purchase request and legal entity."""
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from core.domain.models import Counterparty
from core.services.auth import CurrentUser, get_current_user
from modules.accounting.models import AccessGrant, Organization
from modules.procurement import rfq_scoped, routes
from modules.procurement.models import PurchaseOrder, PurchaseRequest, Rfq, RfqBid, Supplier
from modules.procurement.ownership import PurchaseOwnership

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def rfq_case(client, db, book):
    conn = await db.connection()
    await conn.run_sync(lambda c: Rfq.__table__.create(c))
    await conn.run_sync(lambda c: RfqBid.__table__.create(c))
    await conn.run_sync(lambda c: rfq_scoped.RfqHistory.__table__.create(c))
    await db.commit()
    client.test_app.include_router(routes.router, prefix="/procurement")
    client.test_app.include_router(rfq_scoped.router, prefix="/procurement")

    org2 = Organization(name="Second synthetic company", unp="888888888")
    db.add(org2)
    await db.flush()
    db.add(AccessGrant(organization_id=org2.id, subject="tester", role="chief"))
    request = PurchaseRequest(item="Battery 48V", supplier="", qty=10, stage="sourcing")
    db.add(request)
    await db.flush()
    db.add(PurchaseOwnership(organization_id=book[0], kind="request", source_id=request.id,
        snapshot={"item": request.item}, evidence="Confirmed owner", actor="tester"))
    await db.commit()
    events = []

    class EventBus:
        def emit(self, session, name, payload):
            events.append((name, payload))

    client.test_app.state.core.event_bus = EventBus()
    return book[0], org2.id, request.id, events


def base(org):
    return f"/procurement/organizations/{org}/rfq"


async def test_unscoped_routes_reject_cross_company_access(client, rfq_case, db):
    org, _, request_id, _ = rfq_case
    assert (await client.get("/procurement/rfq")).status_code == 410
    assert (await client.post("/procurement/rfq", json={"item": "Unowned"})).status_code == 410
    assert (await client.get("/procurement/rfq/1")).status_code == 410
    assert (await client.post("/procurement/rfq/1/bids", json={"supplier_id": 1, "price_byn": 3})).status_code == 410
    assert (await client.post("/procurement/rfq/1/award", json={"bid_id": 1})).status_code == 410
    # A legacy RFQ with a soft request reference is not automatically treated as owned.
    db.add(Rfq(item="Old", request_id=request_id, qty=1))
    await db.commit()
    assert (await client.get(base(org))).json()["items"] == []


async def test_scoped_rfq_create_bid_award_and_replay(client, rfq_case, db):
    org, other, request_id, events = rfq_case
    url = base(org)
    key = str(uuid4())
    payload = {"request_key": key, "request_id": request_id}
    assert (await client.post(base(other), json=payload)).status_code == 409
    made = await client.post(url, json=payload)
    assert made.status_code == 201, made.text
    rfq = made.json()
    assert rfq["organization_id"] == org and rfq["request_id"] == request_id
    assert rfq["number"] == f"RFQ-{rfq['id']:06d}"
    assert rfq["item"] == "Battery 48V" and rfq["qty"] == 10
    assert (await client.post(url, json=payload)).json() == rfq
    assert (await db.scalar(select(func.count()).select_from(Rfq))) == 1
    assert (await client.get(base(other))).json()["items"] == []
    assert (await client.get(base(other) + f"/{rfq['id']}")).status_code == 404
    assert (await client.get(base(other) + f"/{rfq['id']}/history")).status_code == 404

    bid = {"bid_key": str(uuid4()), "supplier_id": 1, "price_byn": "120.00"}
    bid_url = url + f"/{rfq['id']}/bids"
    added = await client.post(bid_url, json=bid)
    assert added.status_code == 201, added.text
    assert (await client.post(bid_url, json=bid)).json() == added.json()
    assert (await db.scalar(select(func.count()).select_from(RfqBid))) == 1
    changed = {**bid, "price_byn": "121.00"}
    assert (await client.post(bid_url, json=changed)).status_code == 409
    assert (await client.post(base(other) + f"/{rfq['id']}/bids", json={**bid, "bid_key": str(uuid4())})).status_code == 404

    winner = added.json()["bids"][0]["id"]
    awarded = await client.post(url + f"/{rfq['id']}/award", json={"bid_id": winner})
    assert awarded.status_code == 200, awarded.text
    assert awarded.json()["status"] == "awarded"
    assert (await client.post(url + f"/{rfq['id']}/award", json={"bid_id": winner})).status_code == 200
    assert len(events) == 1 and events[0][1]["organization_id"] == org
    assert (await db.scalar(select(func.count()).select_from(PurchaseOrder))) == 0
    assert (await client.post(bid_url, json={**bid, "bid_key": str(uuid4())})).status_code == 409
    document_history = (await client.get(url + f"/{rfq['id']}/history")).json()
    assert document_history["organization_id"] == org
    assert [row["action"] for row in document_history["items"]] == ["create", "bid", "award"]
    assert all(row["actor"] == "tester" and row["created_at"] for row in document_history["items"])
    assert document_history["items"][-1]["before"] == {"status": "open", "winner_bid_id": None}
    assert document_history["items"][-1]["after"] == {"status": "awarded", "winner_bid_id": winner}


async def test_bid_requires_current_bound_supplier(client, rfq_case, db):
    org, _, request_id, _ = rfq_case
    rfq = (await client.post(base(org), json={"request_key": str(uuid4()), "request_id": request_id})).json()
    bid_url = base(org) + f"/{rfq['id']}/bids"
    bad = {"bid_key": str(uuid4()), "supplier_id": 999, "price_byn": "100.00"}
    assert (await client.post(bid_url, json=bad)).status_code == 409
    assert (await client.post(bid_url, json={**bad, "price_byn": 100.123})).status_code == 422
    party = Counterparty(id=2, name="Other", unp="190000002")
    supplier = Supplier(id=2, name="Other", unp="190000002", counterparty_id=2, status="blocked")
    db.add_all([party, supplier])
    await db.commit()
    assert (await client.post(bid_url, json={**bad, "supplier_id": 2})).status_code == 409
    assert (await db.scalar(select(func.count()).select_from(RfqBid))) == 0


async def test_reader_can_view_but_cannot_change_rfq(client, rfq_case, db):
    org, _, request_id, _ = rfq_case
    rfq = (await client.post(base(org), json={"request_key": str(uuid4()), "request_id": request_id})).json()
    db.add(AccessGrant(organization_id=org, subject="viewer", role="reader"))
    await db.commit()
    client.test_app.dependency_overrides[get_current_user] = lambda: CurrentUser("viewer", ["director"])
    assert (await client.get(base(org))).status_code == 200
    assert (await client.post(base(org), json={"request_key": str(uuid4()), "request_id": request_id})).status_code == 403
    assert (await client.post(base(org) + f"/{rfq['id']}/bids", json={
        "bid_key": str(uuid4()), "supplier_id": 1, "price_byn": "100.00"})).status_code == 403
    assert (await client.post(base(org) + f"/{rfq['id']}/award", json={"bid_id": 1})).status_code == 403
