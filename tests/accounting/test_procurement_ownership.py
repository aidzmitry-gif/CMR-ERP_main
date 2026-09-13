
import pytest
from sqlalchemy import func, select

from core.services.auth import CurrentUser, get_current_user
from modules.accounting.models import AccessGrant, Organization
from modules.procurement.models import PurchaseOrder, PurchaseRequest
from modules.procurement.ownership import OrderRequestLink, PurchaseOwnership


async def legacy_sources(db):
    order = PurchaseOrder(number="PO1", supplier="Synthetic supplier")
    request = PurchaseRequest(number="REQ1", supplier="Synthetic supplier", item="Synthetic item", qty=3, amount="100.00")
    db.add_all([order, request])
    await db.commit()
    return order, request


async def test_explicit_ownership_snapshot_and_request_order_link(client, db, book):
    order, request = await legacy_sources(db)
    prefix = f"/procurement/organizations/{book[0]}"
    assert (await client.get(prefix + "/purchase-ownership")).json() == []
    assignments = []
    for kind, source in [("order", order), ("request", request)]:
        body = {"kind": kind, "source_id": source.id, "evidence": "Synthetic accountant decision"}
        first = await client.post(prefix + "/purchase-ownership", json=body)
        repeat = await client.post(prefix + "/purchase-ownership", json=body)
        assert first.status_code == repeat.status_code == 201
        assert first.json()["id"] == repeat.json()["id"]
        assignments.append(first.json())
    order.supplier = "Changed legacy title"
    await db.commit()
    rows = (await client.get(prefix + "/purchase-ownership")).json()
    assert rows[0]["snapshot"]["supplier"] == "Synthetic supplier"
    body = {"order_id": order.id, "request_id": request.id, "evidence": "Plan request supplied by this order"}
    first = await client.post(prefix + "/order-request-links", json=body)
    repeat = await client.post(prefix + "/order-request-links", json=body)
    assert first.status_code == repeat.status_code == 201
    assert first.json()["id"] == repeat.json()["id"]
    assert await db.scalar(select(func.count()).select_from(OrderRequestLink)) == 1
    assert (await client.post(prefix + "/order-request-links", json={**body, "evidence": "changed"})).status_code == 409
    row = await db.get(PurchaseOwnership, assignments[0]["id"])
    row.evidence = "overwrite"
    with pytest.raises(ValueError, match="immutable"):
        await db.flush()
    await db.rollback()


async def test_ownership_requires_chief_and_existing_source(client, db, book):
    prefix = f"/procurement/organizations/{book[0]}"
    body = {"kind": "order", "source_id": 998, "evidence": "Synthetic decision"}
    assert (await client.post(prefix + "/purchase-ownership", json=body)).status_code == 404
    db.add(AccessGrant(organization_id=book[0], subject="buyer", role="reader"))
    await db.commit()
    client.test_app.dependency_overrides[get_current_user] = lambda: CurrentUser("buyer", ["procurement"])
    assert (await client.post(prefix + "/purchase-ownership", json=body)).status_code == 403
    assert (await client.get(prefix + "/purchase-ownership")).status_code == 200
    assert (await client.post(prefix + "/order-request-links", json={"order_id": 1, "request_id": 1, "evidence": "Not mapped"})).status_code == 409


async def test_other_company_cannot_claim_or_link_sources(client, db, book):
    order, request = await legacy_sources(db)
    order_id, request_id = order.id, request.id
    second = Organization(name="Other synthetic company", unp="999999998")
    db.add(second)
    await db.flush()
    db.add(AccessGrant(organization_id=second.id, subject="tester", role="chief"))
    await db.commit()
    first_path = f"/procurement/organizations/{book[0]}"
    second_path = f"/procurement/organizations/{second.id}"
    body = {"kind": "order", "source_id": order_id, "evidence": "First owner"}
    assert (await client.post(first_path + "/purchase-ownership", json=body)).status_code == 201
    assert (await client.post(second_path + "/purchase-ownership", json=body)).status_code == 409
    assert (await client.post(second_path + "/purchase-ownership", json={"kind": "request", "source_id": request_id, "evidence": "Second owner"})).status_code == 201
    assert (await client.post(first_path + "/order-request-links", json={"order_id": order_id, "request_id": request_id, "evidence": "Cross company"})).status_code == 409
    assert len((await client.get(second_path + "/purchase-ownership")).json()) == 1

async def test_receipt_order_link_is_versioned_and_reaches_posting(client, db, book):
    from modules.procurement.models import PurchaseOrder
    from tests.accounting.test_procurement_receipt_drafts import document, source_options
    prefix = f"/procurement/organizations/{book[0]}"
    path, options = await source_options(client, db, book)
    order = PurchaseOrder(number="PO-LINK", supplier="Synthetic supplier")
    db.add(order)
    await db.commit()
    order_id = order.id
    data = document()
    data["items"][0].update(order_id=order_id, vat_rate="0", vat_amount="0.00")
    # A real order without a company decision must not become a receipt basis.
    assert (await client.put(path, json={"expected_version": 1, "document": data})).status_code == 409
    assert (await client.post(prefix + "/purchase-ownership", json={"kind": "order", "source_id": order_id, "evidence": "Approved synthetic owner"})).status_code == 201
    edited = await client.put(path, json={"expected_version": 1, "document": data})
    assert edited.status_code == 200, edited.text
    assert edited.json()["revisions"][0]["document"]["items"][0].get("order_id") is None
    assert edited.json()["revisions"][1]["document"]["items"][0]["order_id"] == order_id
    preview = await client.post(path + "/preview", json={**options, "expected_version": 2})
    assert preview.status_code == 200, preview.text
    assert preview.json()["lines"][0]["dimensions"]["order"] == str(order_id)
    confirmed = await client.post(path + "/confirm", json={**options, "expected_version": 2, "digest": preview.json()["digest"]})
    assert confirmed.status_code == 201
    entry_id = confirmed.json()["entry_id"]
    details = (await client.get(f"/accounting/organizations/{book[0]}/entries/{entry_id}")).json()
    assert details["lines"][0]["dimensions"]["order"] == str(order_id)

async def test_direct_purchase_api_cannot_bypass_order_ownership(client, db, book):
    from modules.accounting.models import Entry
    from tests.accounting.test_purchase_documents import purchase
    body = purchase(book)
    body["items"][0]["order_id"] = 999
    prefix = f"/accounting/organizations/{book[0]}/purchases"
    for action in ["preview", "confirm"]:
        response = await client.post(prefix + "/" + action, json=body)
        assert response.status_code == 422
        assert "saved procurement receipt" in response.text
    assert await db.scalar(select(func.count()).select_from(Entry)) == 0

async def test_ownership_preview_checks_reviewed_snapshot(client, db, book):
    order, _ = await legacy_sources(db)
    body = {"kind": "order", "source_id": order.id, "evidence": "Reviewed owner"}
    path = f"/procurement/organizations/{book[0]}/purchase-ownership"
    preview = await client.post(path + "/preview", json=body)
    assert preview.status_code == 200
    assert await db.scalar(select(func.count()).select_from(PurchaseOwnership)) == 0
    snapshot = preview.json()["snapshot"]
    order.supplier = "Changed after preview"
    await db.commit()
    response = await client.post(path, json={**body, "expected_snapshot": snapshot})
    assert response.status_code == 409
    assert await db.scalar(select(func.count()).select_from(PurchaseOwnership)) == 0
    updated = (await client.post(path + "/preview", json=body)).json()["snapshot"]
    assert (await client.post(path, json={**body, "expected_snapshot": updated})).status_code == 201

async def test_candidate_search_excludes_assigned_and_pages_literal_query(client, db, book):
    order, _ = await legacy_sources(db)
    order_id = order.id
    other = Organization(name="Other synthetic book", unp="999999998")
    db.add(other)
    await db.flush()
    db.add(PurchaseOwnership(organization_id=other.id, kind="order", source_id=order_id, snapshot={}, evidence="Other owner", actor="tester"))
    db.add_all([PurchaseOrder(number=f"Search-{i:03d}", supplier="Search supplier") for i in range(55)])
    db.add(PurchaseOrder(number="100% literal", supplier="Literal supplier"))
    await db.commit()
    path = f"/procurement/organizations/{book[0]}/purchase-ownership/candidates"
    page = (await client.get(path, params={"kind": "order", "q": "Search"})).json()
    assert len(page["items"]) == 50
    assert page["next_after_id"] == page["items"][-1]["source_id"]
    next_page = (await client.get(path, params={"kind": "order", "q": "Search", "after_id": page["next_after_id"]})).json()
    assert len(next_page["items"]) == 5
    assert next_page["next_after_id"] is None
    assert not ({r["source_id"] for r in page["items"]} & {r["source_id"] for r in next_page["items"]})
    literal = (await client.get(path, params={"kind": "order", "q": "%"})).json()
    assert [r["number"] for r in literal["items"]] == ["100% literal"]
    assigned = (await client.get(path, params={"kind": "order", "q": "PO1"})).json()
    assert assigned["items"] == []
    db.add(AccessGrant(organization_id=book[0], subject="buyer", role="reader"))
    await db.commit()
    client.test_app.dependency_overrides[get_current_user] = lambda: CurrentUser("buyer", ["procurement"])
    assert (await client.get(path, params={"kind": "order"})).status_code == 403

async def test_owned_source_lists_are_scoped_and_keep_exact_line_values(client, db, book):
    from modules.procurement.models import PurchaseOrderLine
    order, request = await legacy_sources(db)
    second = Organization(name="Other list company", unp="999999996")
    db.add(second)
    await db.flush()
    db.add(AccessGrant(organization_id=second.id, subject="tester", role="chief"))
    hidden = PurchaseOrder(number="Hidden", supplier="Foreign")
    unassigned = PurchaseOrder(number="Unassigned", supplier="Unknown")
    db.add_all([hidden, unassigned])
    await db.flush()
    db.add_all([
        PurchaseOwnership(organization_id=book[0], kind="order", source_id=order.id, snapshot={}, evidence="Test", actor="tester"),
        PurchaseOwnership(organization_id=book[0], kind="request", source_id=request.id, snapshot={}, evidence="Test", actor="tester"),
        PurchaseOwnership(organization_id=second.id, kind="order", source_id=hidden.id, snapshot={}, evidence="Test", actor="tester"),
        PurchaseOrderLine(order_id=order.id, sku_code="SKU", qty="1.25", goods_value_byn="90071992547.01"),
    ])
    await db.commit()
    prefix = f"/procurement/organizations/{book[0]}/owned-sources"
    orders = (await client.get(prefix + "?kind=order")).json()
    assert [row["id"] for row in orders["items"]] == [order.id]
    assert orders["items"][0]["lines"][0]["quantity"] == "1.25"
    assert orders["items"][0]["lines"][0]["goods_value_byn"] == "90071992547.01"
    assert orders["next_after_id"] is None
    assert (await client.get(prefix + f"?kind=order&after_id={order.id}")).json()["items"] == []
    requests = (await client.get(prefix + "?kind=request&q=Synthetic%20item")).json()
    assert [row["id"] for row in requests["items"]] == [request.id]
    assert (await client.get(prefix + "?kind=order&q=%25")).json()["items"] == []
    client.test_app.dependency_overrides[get_current_user] = lambda: CurrentUser("stranger", ["director"])
    assert (await client.get(prefix + "?kind=order")).status_code == 403

async def test_legacy_mutations_require_confirmed_company_and_membership(client, db, book, monkeypatch):
    from modules.procurement.routes import router as legacy_router
    client.test_app.include_router(legacy_router, prefix="/procurement")
    order, request = await legacy_sources(db)
    order_id, request_id = order.id, request.id
    routes = [
        ("PATCH", f"/procurement/requests/{request_id}", {"stage": "need"}),
        ("PATCH", f"/procurement/orders/{order_id}", {"status": "ordered"}),
        ("PATCH", f"/procurement/orders/{order_id}/header", {}),
        ("POST", f"/procurement/orders/{order_id}/lines", {"sku_code": "X", "qty": 1, "goods_value_byn": 1}),
        ("DELETE", f"/procurement/orders/{order_id}/lines/1", None),
        ("POST", f"/procurement/orders/{order_id}/plan", {"transport_method_code": "truck", "target_arrival_date": "2026-10-01"}),
    ]
    for method, path, body in routes:
        assert (await client.request(method, path, json=body)).status_code == 409
    for kind, source_id in [("order", order_id), ("request", request_id)]:
        db.add(PurchaseOwnership(organization_id=book[0], kind=kind, source_id=source_id, snapshot={}, evidence="Test", actor="tester"))
    await db.commit()
    client.test_app.dependency_overrides[get_current_user] = lambda: CurrentUser("stranger", ["director"])
    for method, path, body in routes:
        assert (await client.request(method, path, json=body)).status_code == 403
    client.test_app.dependency_overrides[get_current_user] = lambda: CurrentUser("tester", ["director"])
    commits = []
    original_commit = db.commit
    async def tracked_commit():
        commits.append(1)
        await original_commit()
    monkeypatch.setattr(db, "commit", tracked_commit)
    own = await client.patch(f"/procurement/requests/{request_id}", json={"stage": "sourcing"})
    assert own.status_code == 200, own.text
    assert own.json()["stage"] == "sourcing"
    assert len(commits) == 1
