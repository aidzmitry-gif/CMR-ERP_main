from copy import deepcopy
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import event, func, select, update

from core.domain.models import Sku
from core.services.auth import CurrentUser, get_current_user
from modules.accounting.models import AccessGrant, Organization
from modules.procurement import order_creation, routes, scoped_reads
from modules.procurement.models import PurchaseOrder, PurchaseOrderLine, PurchaseRequest, Supplier
from modules.procurement.order_creation import PurchaseOrderCreation
from modules.procurement.ownership import (
    OrderRequestLink,
    PurchaseOwnership,
    PurchaseRequestCreation,
)

HEADERS = {"X-Expected-Principal": "tester"}


@pytest_asyncio.fixture(autouse=True)
async def order_routes(client, db):
    conn = await db.connection()
    await conn.run_sync(lambda c: PurchaseOrderCreation.__table__.create(c))
    await conn.run_sync(lambda c: PurchaseRequestCreation.__table__.create(c))
    await conn.run_sync(lambda c: Supplier.__table__.create(c, checkfirst=True))
    await db.commit()
    client.test_app.include_router(order_creation.router, prefix="/procurement")
    client.test_app.include_router(routes.router, prefix="/procurement")
    client.test_app.include_router(scoped_reads.router, prefix="/procurement")


def command():
    return {"request_key": str(uuid4()), "document": {"supplier": "Поставщик", "eta_date": "2026-10-01", "freight_byn": "10.00", "lines": [
        {"sku_code": "SKU-A", "qty": "1.25", "goods_value_byn": "100.00", "weight": "1.123", "volume": "0.1234"},
        {"sku_code": "SKU-B", "qty": "2.00", "goods_value_byn": "200.00", "weight": "2.000", "volume": "1.0000"}]},
        "ownership_evidence": "Reviewed owner", "request_basis": None}


def prefix(book):
    return f"/procurement/organizations/{book[0]}"


async def create(client, book, data):
    result = await client.post(prefix(book) + "/orders", json=data, headers=HEADERS)
    assert result.status_code == 201, result.text
    return result.json()


async def counts(db):
    return {m.__name__: await db.scalar(select(func.count()).select_from(m)) for m in
            (PurchaseOrder, PurchaseOrderLine, PurchaseOrderCreation, PurchaseOwnership, OrderRequestLink)}


async def approved_request(client, book):
    from tests.accounting.test_procurement_request_creation import command as request_command
    response = await client.post(prefix(book) + "/requests", json=request_command(), headers=HEADERS)
    assert response.status_code == 201, response.text
    request_id = response.json()["request_id"]
    for before, after in zip(("need", "sourcing", "nego", "analysis"), ("sourcing", "nego", "analysis", "approval"), strict=True):
        assert (await client.patch(prefix(book) + f"/requests/{request_id}/stage", json={"expected_stage": before, "stage": after}, headers=HEADERS)).status_code == 200
    response = await client.get(prefix(book) + f"/requests/{request_id}/order-basis")
    assert response.status_code == 200
    return {"request_id": request_id, "expected_stage": "approval", "expected_hash": response.json()["basis_hash"], "link_evidence": "Reviewed supply link"}


async def test_multiline_standalone_exact_creation_and_replay(client, db, book):
    data = command()
    first = await create(client, book, data)
    assert first["outcome"] == "created" and first["status"] == "draft" and first["request_id"] is None
    assert first["lines"][0]["weight"] == "1.123" and first["lines"][0]["volume"] == "0.1234"
    assert (await counts(db)) == {"PurchaseOrder": 1, "PurchaseOrderLine": 2, "PurchaseOrderCreation": 1, "PurchaseOwnership": 1, "OrderRequestLink": 0}
    assert await create(client, book, data) == first
    detail = await client.get(prefix(book) + f"/orders/{first['order_id']}")
    assert detail.status_code == 200 and detail.json()["lines"] == first["lines"]
    assert detail.json()["next_after_line_id"] is None
    listing = await client.get(prefix(book) + "/owned-sources?kind=order")
    assert [x["id"] for x in listing.json()["items"]] == [first["order_id"]]
    changed = deepcopy(data)
    changed["document"]["lines"][0]["qty"] = "3.00"
    assert (await client.post(prefix(book) + "/orders", json=changed, headers=HEADERS)).status_code == 409
    # Historical result remains readable after legitimate current header/line changes.
    await db.execute(update(PurchaseOrder).values(supplier="Later", status="ordered"))
    await db.execute(update(PurchaseOrderLine).values(qty="5.00"))
    await db.commit()
    assert await create(client, book, data) == first
    assert (await client.get(prefix(book) + f"/orders/{first['order_id']}")).json()["status"] == "ordered"


async def test_catalog_selected_lines_keep_immutable_snapshot_and_reject_stale_selection(client, db, book):
    products = [Sku(code="SKU-A", title="Первый товар", unit="шт"),
                Sku(code="SKU-B", title="Второй товар", unit="уп")]
    db.add_all(products)
    await db.commit()
    data = command()
    for line, sku in zip(data["document"]["lines"], products, strict=True):
        line.update(sku_id=sku.id, sku_title=sku.title, sku_unit=sku.unit)
    first = await create(client, book, data)
    assert first["lines"][0]["sku_code"] == "SKU-A" and "sku_id" not in first["lines"][0]
    receipt = await db.scalar(select(PurchaseOrderCreation).where(PurchaseOrderCreation.order_id == first["order_id"]))
    assert receipt.command["document"]["lines"][0]["sku_id"] == products[0].id
    assert receipt.command["document"]["lines"][0]["sku_title"] == "Первый товар"
    products[0].title = "Переименованный товар"
    await db.commit()
    assert await create(client, book, data) == first
    stale = deepcopy(data)
    stale["request_key"] = str(uuid4())
    result = await client.post(prefix(book) + "/orders", json=stale, headers=HEADERS)
    assert result.status_code == 409 and result.json()["code"] == "sku_catalog_changed"
    assert result.json()["no_business_write"] is True
    assert (await counts(db))["PurchaseOrder"] == 1


async def test_incomplete_catalog_reference_rejected_before_receipt(client, db, book):
    data = command()
    data["document"]["lines"][0]["sku_id"] = 99
    result = await client.post(prefix(book) + "/orders", json=data, headers=HEADERS)
    assert result.status_code == 422
    assert (await counts(db))["PurchaseOrderCreation"] == 0


async def test_supplier_selection_is_scoped_and_snapshotted_on_order_creation(client, db, book):
    supplier = Supplier(name="Поставщик А", unp="190000001", status="active")
    blocked = Supplier(name="Заблокированный", unp="190000002", status="blocked")
    db.add_all([supplier, blocked])
    await db.commit()
    supplier_id = supplier.id
    options = await client.get(prefix(book) + "/supplier-options", params={"q": "Поставщик"})
    assert options.status_code == 200
    assert options.json()["items"] == [{"id": supplier_id, "name": "Поставщик А", "unp": "190000001"}]
    other = Organization(name="No access", unp="999999996")
    db.add(other)
    await db.commit()
    assert (await client.get(f"/procurement/organizations/{other.id}/supplier-options")).status_code == 403
    data = command()
    data["document"].update(supplier="Поставщик А", supplier_id=supplier_id, supplier_unp="190000001")
    first = await create(client, book, data)
    row = await db.get(PurchaseOrder, first["order_id"])
    assert row.supplier_id == supplier_id
    receipt = await db.scalar(select(PurchaseOrderCreation).where(PurchaseOrderCreation.order_id == first["order_id"]))
    assert receipt.command["document"]["supplier_unp"] == "190000001"
    supplier.name = "Новое имя"
    await db.commit()
    assert await create(client, book, data) == first
    stale = deepcopy(data)
    stale["request_key"] = str(uuid4())
    rejected = await client.post(prefix(book) + "/orders", json=stale, headers=HEADERS)
    assert rejected.status_code == 409 and rejected.json()["code"] == "supplier_catalog_changed"
    assert rejected.json()["no_business_write"] is True
    assert (await counts(db))["PurchaseOrder"] == 1


async def test_from_request_atomic_link_and_current_basis(client, db, book):
    data = command()
    data["request_basis"] = await approved_request(client, book)
    first = await create(client, book, data)
    assert first["request_id"] == data["request_basis"]["request_id"]
    assert first["request_snapshot"]["stage"] == "approval" and first["link_id"] > 0
    request = await db.get(PurchaseRequest, first["request_id"], populate_existing=True)
    assert request.stage == "po"
    assert await create(client, book, data) == first
    another = {**data, "request_key": str(uuid4())}
    rejected = await client.post(prefix(book) + "/orders", json=another, headers=HEADERS)
    assert rejected.status_code == 409 and rejected.json()["outcome"] == "rejected"
    assert (await counts(db))["PurchaseOrder"] == 1


async def test_stale_basis_definite_outcome_allows_reviewed_new_key(client, db, book):
    data = command()
    data["request_basis"] = await approved_request(client, book)
    request_id = data["request_basis"]["request_id"]
    await db.execute(update(PurchaseRequest).where(PurchaseRequest.id == request_id).values(qty=99))
    await db.commit()
    rejected = await client.post(prefix(book) + "/orders", json=data, headers=HEADERS)
    assert rejected.status_code == 409 and rejected.json()["code"] == "request_basis_changed"
    assert rejected.json()["no_business_write"] is True
    assert (await counts(db))["PurchaseOrder"] == 0
    basis = (await client.get(prefix(book) + f"/requests/{request_id}/order-basis")).json()
    fresh = deepcopy(data)
    fresh["request_key"] = str(uuid4())
    fresh["request_basis"]["expected_hash"] = basis["basis_hash"]
    await create(client, book, fresh)
    # Late old request remains rejected even after a valid new order exists.
    assert (await client.post(prefix(book) + "/orders", json=data, headers=HEADERS)).json() == rejected.json()
    assert (await counts(db))["PurchaseOrder"] == 1


async def test_reconcile_tombstone_prevents_late_commit_and_returns_existing(client, db, book):
    data = command()
    rejected = await client.post(prefix(book) + "/order-commands/reconcile", json=data, headers=HEADERS)
    assert rejected.status_code == 409 and rejected.json()["code"] == "command_abandoned"
    assert (await client.post(prefix(book) + "/orders", json=data, headers=HEADERS)).json() == rejected.json()
    assert (await counts(db))["PurchaseOrder"] == 0
    fresh = command()
    created = await create(client, book, fresh)
    result = await client.post(prefix(book) + "/order-commands/reconcile", json=fresh, headers=HEADERS)
    assert result.status_code == 201 and result.json() == created
    assert (await counts(db))["PurchaseOrder"] == 1


@pytest.mark.parametrize("field,value", [("qty", True), ("qty", 1), ("qty", 1.2), ("qty", "0.00"), ("qty", "1e2"),
    ("qty", "1000000000000.00"), ("goods_value_byn", "1.234"), ("goods_value_byn", "NaN"),
    ("weight", "100000000000.000"), ("weight", "0.0001"), ("volume", "10000000000.0000"),
    ("volume", "-0.0001"), ("sku_code", ""), ("sku_code", "x" * 65), ("sku_code", "A\x00B")])
async def test_order_line_strict_precision(client, db, book, field, value):
    data = command()
    data["document"]["lines"][0][field] = value
    assert (await client.post(prefix(book) + "/orders", json=data, headers=HEADERS)).status_code == 422
    assert (await counts(db))["PurchaseOrder"] == 0
    assert (await counts(db))["PurchaseOrderCreation"] == 0


@pytest.mark.parametrize("field,value", [("eta_date", "infinity"), ("eta_date", "2026-02-30"), ("eta_date", "10000-01-01"),
    ("freight_byn", 1.5), ("freight_byn", "1000000000000.00"), ("supplier", "\u00a0\x1c"), ("status", "received"), ("lines", [])])
async def test_order_header_strict_precision(client, db, book, field, value):
    data = command()
    data["document"][field] = value
    assert (await client.post(prefix(book) + "/orders", json=data, headers=HEADERS)).status_code == 422
    assert (await counts(db))["PurchaseOrderCreation"] == 0


@pytest.mark.parametrize("failure", [PurchaseOrderLine, PurchaseOwnership, OrderRequestLink, PurchaseOrderCreation])
async def test_root_rollback_at_package_boundaries(client, db, book, failure):
    data = command()
    data["request_basis"] = await approved_request(client, book)
    before = await counts(db)
    request_id = data["request_basis"]["request_id"]
    def fail(*args):
        raise ValueError("Synthetic package failure")
    event.listen(failure, "before_insert", fail)
    try:
        response = await client.post(prefix(book) + "/orders", json=data, headers=HEADERS)
        assert response.status_code == 422, response.text
    finally:
        event.remove(failure, "before_insert", fail)
    assert await counts(db) == before
    assert (await db.get(PurchaseRequest, request_id, populate_existing=True)).stage == "approval"


async def test_company_and_current_principal_boundaries(client, db, book):
    data = command()
    first = await create(client, book, data)
    assert (await client.post(prefix(book) + "/orders", json=data, headers={"X-Expected-Principal": "someone-else"})).status_code == 409
    other = Organization(name="Other", unp="999999998")
    db.add(other)
    await db.flush()
    other_id = other.id
    db.add(AccessGrant(organization_id=other_id, subject="tester", role="chief"))
    await db.commit()
    assert (await client.get(f"/procurement/organizations/{other_id}/orders/{first['order_id']}")).status_code == 409
    await db.execute(update(AccessGrant).where(AccessGrant.organization_id == book[0]).values(role="reader"))
    await db.commit()
    for endpoint in ("/orders", "/order-commands/reconcile"):
        assert (await client.post(prefix(book) + endpoint, json=data, headers=HEADERS)).status_code == 403
    assert (await client.get(prefix(book) + f"/orders/{first['order_id']}")).status_code == 200
    for method, endpoint, payload in [("PATCH", f"/orders/{first['order_id']}", {"status": "ordered"}),
        ("PATCH", f"/orders/{first['order_id']}/header", {"supplier": "Change"}),
        ("POST", f"/orders/{first['order_id']}/lines", {"sku_code": "NEW", "qty": 1}),
        ("DELETE", f"/orders/{first['order_id']}/lines/{first['lines'][0]['id']}", None),
        ("POST", f"/orders/{first['order_id']}/plan", {"transport_method_code": "truck", "target_arrival_date": "2026-12-01"})]:
        result = await client.request(method, "/procurement" + endpoint, json=payload)
        assert result.status_code == 403, result.text
    client.test_app.dependency_overrides[get_current_user] = lambda: CurrentUser("tester", ["director"], local_status="suspended")
    assert (await client.post(prefix(book) + "/orders", json=data, headers=HEADERS)).status_code == 403


async def test_duplicate_sku_canonical_whitespace_and_immutable_receipt(client, db, book):
    data = command()
    data["document"]["lines"][1]["sku_code"] = " SKU-A "
    assert (await client.post(prefix(book) + "/orders", json=data, headers=HEADERS)).status_code == 422
    data = command()
    data["document"]["supplier"] = "\x1c Поставщик\u00a0"
    first = await create(client, book, data)
    assert first["supplier"] == "Поставщик"
    data["document"]["supplier"] = "Поставщик"
    assert await create(client, book, data) == first
    row = await db.scalar(select(PurchaseOrderCreation))
    row.outcome = "rejected"
    with pytest.raises(ValueError, match="immutable"):
        await db.flush()
    await db.rollback()

async def test_request_id_integer_bound_rejected_before_tombstone(client, db, book):
    data = command()
    data["request_basis"] = {"request_id": 2147483648, "expected_stage": "approval", "expected_hash": "a" * 64, "link_evidence": "Proof"}
    for endpoint in ("/orders", "/order-commands/reconcile"):
        assert (await client.post(prefix(book) + endpoint, json=data, headers=HEADERS)).status_code == 422
    assert (await counts(db))["PurchaseOrderCreation"] == 0


async def test_two_organizations_may_use_same_key_and_reconcile_is_scoped(client, db, book):
    data = command()
    first = await create(client, book, data)
    other = Organization(name="Other", unp="999999997")
    db.add(other)
    await db.flush()
    other_id = other.id
    db.add(AccessGrant(organization_id=other_id, subject="tester", role="chief"))
    await db.commit()
    second = await create(client, (other_id,), data)
    assert first["order_id"] != second["order_id"]
    assert (await client.post(prefix((other_id,)) + "/order-commands/reconcile", json=data, headers=HEADERS)).json() == second


async def test_detail_paginates_legacy_lines_without_losing_precision(client, db, book):
    first = await create(client, book, command())
    db.add_all([PurchaseOrderLine(order_id=first["order_id"], sku_code=f"EXTRA-{i}", qty="1.01", goods_value_byn="0.01", weight="0.001", volume="0.0001") for i in range(200)])
    await db.commit()
    path = prefix(book) + f"/orders/{first['order_id']}"
    page = (await client.get(path)).json()
    assert len(page["lines"]) == 200 and page["next_after_line_id"] is not None
    tail = (await client.get(path + f"?after_line_id={page['next_after_line_id']}")).json()
    assert len(tail["lines"]) == 2 and tail["next_after_line_id"] is None
    assert tail["lines"][0]["qty"] == "1.01" and tail["lines"][0]["volume"] == "0.0001"


async def test_tampered_receipt_cannot_prove_no_write(client, db, book):
    data = command()
    await create(client, book, data)
    await db.execute(update(PurchaseOrderCreation).values(command_hash="0" * 64))
    await db.commit()
    for endpoint in ("/orders", "/order-commands/reconcile"):
        result = await client.post(prefix(book) + endpoint, json=data, headers=HEADERS)
        assert result.status_code == 409 and "outcome" not in result.json()
