from copy import deepcopy
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import event, func, select, update

from core.services.auth import CurrentUser, get_current_user
from modules.accounting.models import AccessGrant, Organization
from modules.procurement.models import PurchaseOrder, PurchaseRequest
from modules.procurement.ownership import (
    OrderRequestLink,
    PurchaseOwnership,
    PurchaseRequestCreation,
)

HEADERS = {"X-Expected-Principal": "tester"}


@pytest_asyncio.fixture(autouse=True)
async def creation_schema(db):
    connection = await db.connection()
    await connection.run_sync(lambda c: PurchaseRequestCreation.__table__.create(c))
    await db.commit()


def command():
    return {"request_key": str(uuid4()), "document": {"supplier": "Поставщик", "item": "Деталь", "qty": 3,
            "amount": "120.50", "due_date": "2026-10-01"}, "ownership_evidence": "Решение главного бухгалтера"}


def path(book):
    return f"/procurement/organizations/{book[0]}/requests"


async def create(client, book, body=None):
    response = await client.post(path(book), json=body or command(), headers=HEADERS)
    assert response.status_code == 201, response.text
    return response.json()


async def test_atomic_creation_owned_list_and_historical_replay(client, db, book):
    body = command()
    first = await create(client, book, body)
    row = await db.get(PurchaseRequest, first["request_id"])
    assert row.stage == "need" and row.origin == "" and row.qty == 3
    assert str(row.amount) == "120.50"
    owner = await db.get(PurchaseOwnership, first["ownership_id"])
    assert owner.organization_id == book[0] and owner.source_id == row.id and owner.kind == "request"
    assert owner.snapshot["item"] == "Деталь"
    stage = await client.patch(path(book) + f'/{row.id}/stage', json={"expected_stage": "need", "stage": "sourcing"}, headers=HEADERS)
    assert stage.status_code == 200, stage.text
    assert await create(client, book, body) == first
    listing = (await client.get(f"/procurement/organizations/{book[0]}/owned-sources?kind=request")).json()
    assert listing["items"][0]["stage"] == "sourcing"
    for model in (PurchaseRequest, PurchaseOwnership, PurchaseRequestCreation):
        assert await db.scalar(select(func.count()).select_from(model)) == 1
    changed = deepcopy(body)
    changed["document"]["qty"] = 4
    assert (await client.post(path(book), json=changed, headers=HEADERS)).status_code == 409


async def test_canonical_unicode_whitespace_and_empty_rejection(client, db, book):
    whitespace = "".join(chr(n) for n in range(0x110000) if chr(n).isspace())
    body = command()
    body["document"]["supplier"] = whitespace + "Поставщик\u001cвнутри" + whitespace
    body["document"]["item"] = whitespace + "Деталь" + whitespace
    body["ownership_evidence"] = whitespace + "Основание" + whitespace
    receipt = await create(client, book, body)
    row = await db.get(PurchaseRequest, receipt["request_id"])
    owner = await db.get(PurchaseOwnership, receipt["ownership_id"])
    assert row.supplier == "Поставщик\u001cвнутри" and row.item == "Деталь"
    assert owner.evidence == "Основание"
    canonical = deepcopy(body)
    canonical["document"]["supplier"] = row.supplier
    canonical["document"]["item"] = row.item
    canonical["ownership_evidence"] = owner.evidence
    assert await create(client, book, canonical) == receipt
    for field in ("supplier", "item", "ownership_evidence"):
        invalid = command()
        (invalid if field == "ownership_evidence" else invalid["document"])[field] = "\u001c\u001f"
        assert (await client.post(path(book), json=invalid, headers=HEADERS)).status_code == 422
    assert await db.scalar(select(func.count()).select_from(PurchaseRequest)) == 1


@pytest.mark.parametrize("field,value", [("qty", True), ("qty", 1.0), ("qty", "1"), ("qty", 0), ("qty", 2147483648),
    ("amount", 1), ("amount", 1.2), ("amount", True), ("amount", "NaN"), ("amount", "1.234"),
    ("amount", "1000000000000.00"), ("amount", "-1.00"), ("amount", "1e2"), ("amount", "01.00"),
    ("due_date", "2026-02-30"), ("due_date", "20261001"), ("supplier", " "), ("item", "a" * 256),
    ("stage", "qc"), ("origin", "deficit"), ("organization_id", 99)])
async def test_strict_document_rejection(client, db, book, field, value):
    body = command()
    body["document"][field] = value
    assert (await client.post(path(book), json=body, headers=HEADERS)).status_code == 422
    assert await db.scalar(select(func.count()).select_from(PurchaseRequest)) == 0


@pytest.mark.parametrize("key", ["not-a-uuid", "00000000000000000000000000000000", "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA"])
async def test_canonical_key_required(client, book, key):
    body = command()
    body["request_key"] = key
    assert (await client.post(path(book), json=body, headers=HEADERS)).status_code == 422


async def test_current_authorization_before_replay(client, db, book):
    body = command()
    await create(client, book, body)
    assert (await client.post(path(book), json=body)).status_code == 422
    assert (await client.post(path(book), json=body, headers={"X-Expected-Principal": "old-user"})).status_code == 409
    for user in [CurrentUser("tester", ["sales"]), CurrentUser("tester", ["director"], local_status="suspended")]:
        client.test_app.dependency_overrides[get_current_user] = lambda: user
        assert (await client.post(path(book), json=body, headers=HEADERS)).status_code == 403
    client.test_app.dependency_overrides[get_current_user] = lambda: CurrentUser("tester", ["director"])
    await db.execute(update(AccessGrant).where(AccessGrant.organization_id == book[0]).values(role="reader"))
    await db.commit()
    context = await client.get(f"/procurement/organizations/{book[0]}/request-plan-context")
    assert context.json() == {"organization_id": book[0], "principal": "tester", "can_manage": False}
    assert (await client.post(path(book), json=body, headers=HEADERS)).status_code == 403


async def test_separate_organizations_same_key_and_no_cross_link(client, db, book):
    body = command()
    first = await create(client, book, body)
    other = Organization(name="Other", unp="999999998")
    db.add(other)
    await db.flush()
    second_id = other.id
    db.add(AccessGrant(organization_id=second_id, subject="tester", role="chief"))
    await db.commit()
    second = await create(client, (second_id,), body)
    assert first["request_id"] != second["request_id"]
    foreign = f"/procurement/organizations/{second_id}/requests/{first['request_id']}/stage"
    assert (await client.patch(foreign, json={"expected_stage": "need", "stage": "sourcing"}, headers=HEADERS)).status_code == 409
    ids = [r["id"] for r in (await client.get(f"/procurement/organizations/{second_id}/owned-sources?kind=request")).json()["items"]]
    assert ids == [second["request_id"]]


async def test_creation_failure_rolls_back_all_three_records(client, db, book):
    def fail(*args):
        raise ValueError("synthetic receipt failure")
    event.listen(PurchaseRequestCreation, "before_insert", fail)
    try:
        assert (await client.post(path(book), json=command(), headers=HEADERS)).status_code == 422
    finally:
        event.remove(PurchaseRequestCreation, "before_insert", fail)
    for model in (PurchaseRequest, PurchaseOwnership, PurchaseRequestCreation):
        assert await db.scalar(select(func.count()).select_from(model)) == 0


async def test_stage_cas_and_existing_order_link(client, db, book):
    first = await create(client, book)
    route = path(book) + f"/{first['request_id']}"
    for target in ("po", "supply", "qc", "done"):
        assert (await client.patch(route + "/stage", json={"expected_stage": "need", "stage": target}, headers=HEADERS)).status_code == 422
    assert (await client.patch(route + "/stage", json={"expected_stage": "need", "stage": "approval"}, headers=HEADERS)).status_code == 409
    for before, after in [("need", "sourcing"), ("sourcing", "nego"), ("nego", "analysis"), ("analysis", "approval")]:
        body = {"expected_stage": before, "stage": after}
        assert (await client.patch(route + "/stage", json=body, headers=HEADERS)).status_code == 200
        assert (await client.patch(route + "/stage", json=body, headers=HEADERS)).status_code == 200
    assert (await client.patch(route + "/stage", json={"expected_stage": "need", "stage": "sourcing"}, headers=HEADERS)).status_code == 409
    order = PurchaseOrder(number="PO-1", supplier="Supplier")
    db.add(order)
    await db.flush()
    order_id = order.id
    await db.commit()
    link_body = {"expected_stage": "approval", "order_id": order_id, "evidence": "Approved link"}
    assert (await client.post(route + "/order-link", json=link_body, headers=HEADERS)).status_code == 409
    mapped = await client.post(f"/procurement/organizations/{book[0]}/purchase-ownership", json={"kind": "order", "source_id": order_id, "evidence": "Owner"})
    assert mapped.status_code == 201
    linked = await client.post(route + "/order-link", json=link_body, headers=HEADERS)
    assert linked.status_code == 201, linked.text
    assert (await client.post(route + "/order-link", json=link_body, headers=HEADERS)).json() == linked.json()
    assert (await client.post(route + "/order-link", json={**link_body, "evidence": "Changed"}, headers=HEADERS)).status_code == 409
    request = await db.get(PurchaseRequest, first["request_id"], populate_existing=True)
    assert request.stage == "po"
    assert await db.scalar(select(func.count()).select_from(OrderRequestLink)) == 1


async def test_immutable_receipt_and_corrupt_hash_fail_closed(client, db, book):
    body = command()
    await create(client, book, body)
    receipt = await db.scalar(select(PurchaseRequestCreation))
    receipt.actor = "tampered"
    with pytest.raises(ValueError, match="immutable"):
        await db.flush()
    await db.rollback()
    # SQLite raw SQL intentionally lacks the proposed PG immutable guards.
    await db.execute(update(PurchaseRequestCreation).values(command_hash="0" * 64))
    await db.commit()
    assert (await client.post(path(book), json=body, headers=HEADERS)).status_code == 409

async def test_link_failure_rolls_back_stage_and_link(client, db, book):
    receipt = await create(client, book)
    request_id = receipt["request_id"]
    await db.execute(update(PurchaseRequest).where(PurchaseRequest.id == request_id).values(stage="approval"))
    order = PurchaseOrder(number="PO-ROLLBACK", supplier="Supplier")
    db.add(order)
    await db.flush()
    order_id = order.id
    db.add(PurchaseOwnership(organization_id=book[0], kind="order", source_id=order_id,
                            snapshot={}, evidence="Owner", actor="tester"))
    await db.commit()
    def fail(*args):
        raise ValueError("synthetic link failure")
    event.listen(OrderRequestLink, "before_insert", fail)
    try:
        result = await client.post(path(book) + f"/{request_id}/order-link", headers=HEADERS,
                                   json={"expected_stage": "approval", "order_id": order_id, "evidence": "Link"})
        assert result.status_code == 422
    finally:
        event.remove(OrderRequestLink, "before_insert", fail)
    assert (await db.get(PurchaseRequest, request_id, populate_existing=True)).stage == "approval"
    assert await db.scalar(select(func.count()).select_from(OrderRequestLink)) == 0


async def test_cancelled_and_other_company_orders_are_rejected(client, db, book):
    receipt = await create(client, book)
    request_id = receipt["request_id"]
    await db.execute(update(PurchaseRequest).where(PurchaseRequest.id == request_id).values(stage="approval"))
    order = PurchaseOrder(number="PO-CANCELLED", supplier="Supplier", status="cancelled")
    db.add(order)
    await db.flush()
    order_id = order.id
    db.add(PurchaseOwnership(organization_id=book[0], kind="order", source_id=order_id,
                            snapshot={}, evidence="Owner", actor="tester"))
    await db.commit()
    link = {"expected_stage": "approval", "order_id": order_id, "evidence": "Link"}
    route = path(book) + f"/{request_id}/order-link"
    assert (await client.post(route, json=link, headers=HEADERS)).status_code == 409
    other = Organization(name="Other", unp="999999998")
    db.add(other)
    await db.flush()
    other_id = other.id
    await db.execute(update(PurchaseOwnership).where(PurchaseOwnership.kind == "order").values(organization_id=other_id))
    await db.execute(update(PurchaseOrder).where(PurchaseOrder.id == order_id).values(status="draft"))
    await db.commit()
    assert (await client.post(route, json=link, headers=HEADERS)).status_code == 409
    assert (await db.get(PurchaseRequest, request_id, populate_existing=True)).stage == "approval"


@pytest.mark.parametrize("field,value", [("result", {"stage": "po"}), ("command", {}), ("ownership_id", 998)])
async def test_corrupt_receipt_references_rejected(client, db, book, field, value):
    body = command()
    await create(client, book, body)
    await db.execute(update(PurchaseRequestCreation).values(**{field: value}))
    await db.commit()
    assert (await client.post(path(book), json=body, headers=HEADERS)).status_code == 409


async def test_later_request_edits_do_not_rewrite_creation_history(client, db, book):
    body = command()
    first = await create(client, book, body)
    await db.execute(update(PurchaseRequest).where(PurchaseRequest.id == first["request_id"]).values(
        supplier="Later correction", qty=12, amount="200.00", stage="approval", due_date="2026-12-31"))
    await db.commit()
    assert await create(client, book, body) == first
