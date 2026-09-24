"""New supplier claims have explicit company and supplier identities."""
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from core.domain.models import Counterparty
from core.services.auth import CurrentUser, get_current_user
from modules.accounting.models import AccessGrant, Organization
from modules.procurement.models import PurchaseOrder, Supplier, SupplierClaim
from modules.procurement.ownership import PurchaseOwnership
from modules.procurement.scoped_claims import ClaimEdit, ClaimOwnership, router

pytestmark = pytest.mark.asyncio
HEADERS = {"X-Expected-Principal": "tester"}


@pytest_asyncio.fixture
async def claims_case(client, db, book):
    conn = await db.connection()
    await conn.run_sync(lambda c: Supplier.__table__.create(c, checkfirst=True))
    await conn.run_sync(lambda c: SupplierClaim.__table__.create(c, checkfirst=True))
    await conn.run_sync(lambda c: ClaimOwnership.__table__.create(c, checkfirst=True))
    await conn.run_sync(lambda c: ClaimEdit.__table__.create(c, checkfirst=True))
    await db.commit()
    client.test_app.include_router(router, prefix="/procurement")
    client.test_app.state.emitted_claim_events = []
    client.test_app.state.core.event_bus = SimpleNamespace(emit=lambda _db, name, payload:
        client.test_app.state.emitted_claim_events.append((name, payload)))
    party = Counterparty(name="Vendor A", unp="299999001")
    db.add(party)
    await db.flush()
    vendor = Supplier(name="Vendor A", unp="299999001", status="active", counterparty_id=party.id)
    other = Organization(name="Other claim company", unp="888888888")
    db.add_all([vendor, other])
    await db.flush()
    db.add(AccessGrant(organization_id=other.id, subject="tester", role="chief"))
    await db.commit()
    return book[0], other.id, vendor.id


def command(supplier_id, **changes):
    data = {"claim_key": str(uuid4()), "supplier_id": supplier_id, "supplier": "Vendor A",
            "supplier_unp": "299999001", "item": "Battery", "reason": "Damaged cell",
            "claim_type": "брак", "qty_affected": 1, "amount_byn": "20.00",
            "ownership_evidence": "Checked primary quality act"}
    data.update(changes)
    return data


async def test_new_claim_is_owned_replayable_and_not_visible_in_other_book(client, db, claims_case):
    org, other, supplier_id = claims_case
    db.add(SupplierClaim(supplier_id=supplier_id, supplier="Vendor A", item="Unassigned scrap",
                         status="open", source="production"))
    await db.commit()
    payload = command(supplier_id)
    path = f"/procurement/organizations/{org}/claims"
    first = await client.post(path, json=payload, headers=HEADERS)
    assert first.status_code == 201, first.text
    result = first.json()
    assert result["organization_id"] == org
    assert result["claim"]["supplier_id"] == supplier_id
    assert result["claim"]["source"] == "manual"
    assert result["ownership"]["actor"] == "tester"
    assert (await client.post(path, json=payload, headers=HEADERS)).json() == result
    assert await db.scalar(select(func.count()).select_from(SupplierClaim)) == 2
    assert await db.scalar(select(func.count()).select_from(ClaimOwnership)) == 1
    changed = command(supplier_id, claim_key=payload["claim_key"], reason="Other reason")
    assert (await client.post(path, json=changed, headers=HEADERS)).status_code == 409
    assert [row["claim"]["id"] for row in (await client.get(path)).json()["items"]] == [result["claim"]["id"]]
    assert (await client.get(f"/procurement/organizations/{other}/claims")).json()["items"] == []
    assert (await client.get(f"/procurement/organizations/{other}/claims/{result['claim']['id']}")).status_code == 404


async def test_order_must_be_owned_by_company_and_same_supplier(client, db, claims_case):
    org, other, supplier_id = claims_case
    order = PurchaseOrder(number="PO-CLAIM", supplier="Vendor A", supplier_id=supplier_id, status="ordered")
    db.add(order)
    await db.flush()
    db.add(PurchaseOwnership(organization_id=other, kind="order", source_id=order.id,
                             snapshot={}, evidence="Checked", actor="tester"))
    await db.commit()
    path = f"/procurement/organizations/{org}/claims"
    assert (await client.post(path, json=command(supplier_id, order_id=order.id), headers=HEADERS)).status_code == 409
    assert await db.scalar(select(func.count()).select_from(SupplierClaim)) == 0
    own_order = PurchaseOrder(number="PO-OWN", supplier="Vendor A", supplier_id=supplier_id, status="ordered")
    db.add(own_order)
    await db.flush()
    db.add(PurchaseOwnership(organization_id=org, kind="order", source_id=own_order.id,
                             snapshot={}, evidence="Checked", actor="tester"))
    await db.commit()
    response = await client.post(path, json=command(supplier_id, order_id=own_order.id), headers=HEADERS)
    assert response.status_code == 201, response.text
    assert response.json()["order_id"] == own_order.id
    assert response.json()["claim"]["order_code"] == "PO-OWN"


async def test_claim_rejects_stale_supplier_and_reader_write(client, db, claims_case):
    org, _, supplier_id = claims_case
    path = f"/procurement/organizations/{org}/claims"
    assert (await client.post(path, json=command(supplier_id, supplier="Renamed"), headers=HEADERS)).status_code == 409
    db.add(AccessGrant(organization_id=org, subject="reader", role="reader"))
    await db.commit()
    client.test_app.dependency_overrides[get_current_user] = lambda: CurrentUser("reader", ["director"])
    assert (await client.post(path, json=command(supplier_id),
                              headers={"X-Expected-Principal": "reader"})).status_code == 403
    assert (await client.get(path)).status_code == 200
    assert await db.scalar(select(func.count()).select_from(SupplierClaim)) == 0


async def test_resolution_has_one_company_event_and_immutable_before_after(client, db, claims_case):
    org, other, supplier_id = claims_case
    created = (await client.post(f"/procurement/organizations/{org}/claims",
                                 json=command(supplier_id), headers=HEADERS)).json()
    claim_id = created["claim"]["id"]
    path = f"/procurement/organizations/{org}/claims/{claim_id}/resolve"
    command_body = {"edit_key": str(uuid4()), "expected_status": "open",
                    "status": "resolved", "resolution": "Replacement received"}
    first = await client.post(path, json=command_body, headers=HEADERS)
    assert first.status_code == 200, first.text
    assert first.json()["claim"]["status"] == "resolved"
    assert (await client.post(path, json=command_body, headers=HEADERS)).json() == first.json()
    assert await db.scalar(select(func.count()).select_from(ClaimEdit)) == 1
    assert len(client.test_app.state.emitted_claim_events) == 1
    name, emitted = client.test_app.state.emitted_claim_events[0]
    assert name == "procurement.claim.resolution_recorded"
    assert emitted["organization_id"] == org and emitted["claim_id"] == claim_id
    changed = {**command_body, "resolution": "Different"}
    assert (await client.post(path, json=changed, headers=HEADERS)).status_code == 409
    assert (await client.post(path, json={**command_body, "edit_key": str(uuid4())},
                              headers=HEADERS)).status_code == 409
    history = (await client.get(f"/procurement/organizations/{org}/claims/{claim_id}/history")).json()
    assert history["created"]["actor"] == "tester"
    assert history["edits"][0]["before"] == {"status": "open", "resolution": ""}
    assert history["edits"][0]["after"] == {"status": "resolved", "resolution": "Replacement received"}
    assert (await client.get(f"/procurement/organizations/{other}/claims/{claim_id}/history")).status_code == 404
