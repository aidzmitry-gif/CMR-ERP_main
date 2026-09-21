from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from modules.wms.events import on_goods_received
from modules.wms.models import Location, Receipt, StockMovement, Task
from tests.reservation_source import event_context, invoice


async def book(api):
    api.headers["X-User"] = "wms-owner-test"
    response = await api.post("/accounting/organizations", json={"name": "Synthetic WMS company", "unp": "999999993"})
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def test_receipt_company_flows_to_receipt_and_putaway_movements(api, session):
    org = await book(api)
    await on_goods_received({"organization_id": org, "sku_code": "A", "qty": "1.25", "warehouse": "Test", "entity_ref": "purchase_order:1:1"}, SimpleNamespace(session=session))
    await session.commit()
    receipt_id = await session.scalar(select(Receipt.id))
    denied = await api.post(f"/wms/receipts/{receipt_id}/accept", headers={"X-User": "other"})
    assert denied.status_code == 403
    accepted = await api.post(f"/wms/receipts/{receipt_id}/accept")
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["organization_id"] == org
    assert (await api.post(f"/wms/receipts/{receipt_id}/accept")).status_code == 200
    task = await session.scalar(select(Task))
    task_id = task.id
    assert task.organization_id == org
    location = Location(warehouse="Test", code="CELL", title="Synthetic")
    session.add(location)
    await session.commit()
    location_id = location.id
    assert (await api.patch(f"/wms/tasks/{task_id}", headers={"X-User": "other"}, json={"status": "done", "to_location_id": location_id})).status_code == 403
    completed = await api.patch(f"/wms/tasks/{task_id}", json={"status": "done", "to_location_id": location_id})
    assert completed.status_code == 200, completed.text
    movements = (await session.scalars(select(StockMovement))).all()
    assert len(movements) == 3
    assert all(row.organization_id == org and row.qty == Decimal("1.25") for row in movements)


async def test_legacy_receipt_requires_explicit_chief_ownership(api, session):
    org = await book(api)
    await on_goods_received({"item": "A", "qty": 1, "entity_ref": "purchase:old"}, SimpleNamespace(session=session))
    await session.commit()
    receipt_id = await session.scalar(select(Receipt.id))
    assert (await api.post(f"/wms/receipts/{receipt_id}/accept")).status_code == 409
    mapped = await api.post(f"/wms/receipts/{receipt_id}/organization", json={"organization_id": org, "evidence": "Synthetic owner verification"})
    assert mapped.status_code == 200, mapped.text
    assert mapped.json()["organization_id"] == org
    assert (await api.post(f"/wms/receipts/{receipt_id}/accept")).status_code == 200


@pytest.mark.parametrize("org", [True, "1", 0, -1])
async def test_receipt_event_rejects_invalid_company(session, org):
    with pytest.raises(ValueError, match="organization_id"):
        await on_goods_received({"organization_id": org, "item": "A", "qty": 1}, SimpleNamespace(session=session))
    assert await session.scalar(select(Receipt.id)) is None


async def test_outbox_replay_uses_event_identity_not_same_source_text(session):
    from core.domain.models import OutboxEvent
    from core.services.eventbus import EventContext, OutboxEventBus

    bus = OutboxEventBus()
    bus.subscribe("procurement.received", on_goods_received)
    payload = {"item": "A", "qty": "1.25", "entity_ref": "purchase_order:1:1"}
    bus.emit(session, "procurement.received", payload)
    await session.commit()
    event = await session.scalar(select(OutboxEvent))
    event_id = event.id
    ctx = EventContext(session, None)
    assert await bus.relay_once(session, ctx) == 1
    # Operator replay of the same durable event must leave one receipt/line.
    event.processed_at = None
    await session.commit()
    assert await bus.relay_once(session, ctx) == 1
    receipts = (await session.scalars(select(Receipt))).all()
    assert len(receipts) == 1 and receipts[0].source_event_id == event_id
    # A distinct event with identical document text is not silently discarded.
    bus.emit(session, "procurement.received", payload)
    await session.commit()
    assert await bus.relay_once(session, ctx) == 1
    assert len((await session.scalars(select(Receipt))).all()) == 2
    assert ctx.event_id is None


async def test_missing_receipt_context_keeps_outbox_pending_for_retry(session):
    from core.domain.models import AuditLog, OutboxEvent
    from core.services.eventbus import EventContext, OutboxEventBus

    bus = OutboxEventBus()
    bus.subscribe("procurement.received", on_goods_received)
    bus.emit(session, "procurement.received", {"item": "A", "qty": "1.25"})
    await session.commit()
    with pytest.raises(ValueError, match="EventContext is required"):
        await bus.relay_once(session)
    await session.rollback()
    event = await session.scalar(select(OutboxEvent))
    assert event.processed_at is None
    assert await session.scalar(select(Receipt.id)) is None
    assert await session.scalar(select(AuditLog.id)) is None
    assert await bus.relay_once(session, EventContext(session, None)) == 1
    assert len((await session.scalars(select(Receipt))).all()) == 1


@pytest.mark.parametrize("qty", [None, True, "invalid", "NaN", "Infinity", "-Infinity", "0", "-1", "0.001", "1000000000000"])
async def test_receipt_rejects_unrepresentable_quantities_before_writes(session, qty):
    with pytest.raises(ValueError, match="quantity"):
        await on_goods_received({"item": "A", "qty": qty}, SimpleNamespace(session=session))
    assert await session.scalar(select(Receipt.id)) is None


@pytest.mark.parametrize("sku", [None, "", "   ", 123, "A" * 65])
async def test_receipt_rejects_missing_or_invalid_sku(session, sku):
    with pytest.raises(ValueError, match="SKU"):
        await on_goods_received({"item": sku, "qty": "1"}, SimpleNamespace(session=session))
    assert await session.scalar(select(Receipt.id)) is None


@pytest.mark.parametrize("qty", ["0.01", "1.2500", "999999999999.99"])
async def test_receipt_quantity_boundaries_are_stored_exactly(session, qty):
    from modules.wms.models import ReceiptLine

    await on_goods_received({"item": "A", "qty": qty}, SimpleNamespace(session=session))
    await session.flush()
    line = await session.scalar(select(ReceiptLine))
    assert line.expected_qty == Decimal(qty)


@pytest.mark.parametrize("field,value", [
    ("warehouse", None), ("warehouse", ""), ("warehouse", "   "),
    ("warehouse", 123), ("warehouse", "W" * 129),
    ("entity_ref", None), ("entity_ref", 123), ("entity_ref", "R" * 129),
])
async def test_receipt_event_rejects_invalid_routing_before_database_access(field, value):
    # No session at all: malformed routing must fail before queries or writes.
    with pytest.raises(ValueError, match=field):
        await on_goods_received({"item": "A", "qty": "1.25", field: value}, SimpleNamespace(session=None))


async def test_receipt_event_preserves_routing_at_storage_limits(session):
    await on_goods_received(
        {"item": "A", "qty": "1.25", "warehouse": "W" * 128, "entity_ref": "purchase:" + "R" * 119},
        SimpleNamespace(session=session),
    )
    receipt = await session.scalar(select(Receipt))
    assert receipt.warehouse == "W" * 128
    assert receipt.entity_ref == "purchase:" + "R" * 119
    assert receipt.source == "procurement"


async def test_receipt_reads_exclude_foreign_and_unassigned_documents(api, session):
    org = await book(api)
    response = await api.post("/accounting/organizations", headers={"X-User": "foreign-wms-user"}, json={"name": "Foreign synthetic", "unp": "999999992"})
    assert response.status_code == 201, response.text
    foreign = response.json()["id"]
    available = await api.get("/wms/receipt-organizations")
    assert available.status_code == 200, available.text
    assert [row["id"] for row in available.json()] == [org]
    receipts = [Receipt(organization_id=value, source="manual", warehouse="Shared", status="pending_qc") for value in [org, foreign, None]]
    session.add_all(receipts)
    await session.commit()
    own_id, foreign_id, unknown_id = [row.id for row in receipts]
    listed = await api.get("/wms/receipts", params={"warehouse": "Shared", "status": "pending_qc"})
    assert listed.status_code == 200, listed.text
    assert [row["id"] for row in listed.json()] == [own_id]
    assert (await api.get("/wms/receipts", params={"organization_id": foreign})).status_code == 403
    assert (await api.get(f"/wms/receipts/{own_id}")).status_code == 200
    assert (await api.get(f"/wms/receipts/{foreign_id}")).status_code == 403
    assert (await api.get(f"/wms/receipts/{unknown_id}")).status_code == 409
    assert (await api.get("/wms/receipts", headers={"X-User": "no-book-access"})).json() == []


async def test_chief_reconciliation_queue_is_paged_and_rechecks_assignment(api, session):
    from modules.accounting.models import AccessGrant
    from modules.wms.models import ReceiptLine

    org = await book(api)
    rows = [Receipt(source="manual", warehouse="Synthetic", status="pending_qc") for _ in range(53)]
    session.add_all(rows)
    session.add_all([Receipt(organization_id=org, status="pending_qc"), Receipt(status="accepted")])
    session.add(AccessGrant(organization_id=org, subject="reader-wms", role="reader"))
    await session.flush()
    receipt_id = rows[0].id
    session.add(ReceiptLine(receipt_id=receipt_id, sku_code="A", expected_qty=Decimal("1.25")))
    await session.commit()
    params = {"organization_id": org}
    assert (await api.get("/wms/receipts-unassigned", params=params, headers={"X-User": "reader-wms"})).status_code == 403
    assert (await api.get(f"/wms/receipts-unassigned/{receipt_id}", params=params, headers={"X-User": "reader-wms"})).status_code == 403
    first = await api.get("/wms/receipts-unassigned", params=params)
    assert first.status_code == 200, first.text
    assert len(first.json()["items"]) == 50
    second = await api.get("/wms/receipts-unassigned", params={**params, "after_id": first.json()["next_after_id"]})
    assert len(second.json()["items"]) == 3
    assert second.json()["next_after_id"] is None
    assert not ({row["id"] for row in first.json()["items"]} & {row["id"] for row in second.json()["items"]})
    detail = await api.get(f"/wms/receipts-unassigned/{receipt_id}", params=params)
    assert detail.status_code == 200
    assert detail.json()["organization_id"] is None
    assert detail.json()["lines"][0]["expected_qty"] == 1.25
    assigned = await api.post(f"/wms/receipts/{receipt_id}/organization", json={"organization_id": org, "evidence": "Synthetic document owner checked"})
    assert assigned.status_code == 200, assigned.text
    assert (await api.get(f"/wms/receipts-unassigned/{receipt_id}", params=params)).status_code == 404
    assert receipt_id not in [row["id"] for row in (await api.get("/wms/receipts-unassigned", params=params)).json()["items"]]


async def test_qc_rejects_invalid_quantities_and_mixed_foreign_lines_atomically(api, session):
    from modules.wms.models import ReceiptLine

    org = await book(api)
    receipt = Receipt(organization_id=org, status="pending_qc")
    other = Receipt(organization_id=org, status="pending_qc")
    session.add_all([receipt, other])
    await session.flush()
    line = ReceiptLine(receipt_id=receipt.id, sku_code="A", expected_qty="10")
    foreign_line = ReceiptLine(receipt_id=other.id, sku_code="B", expected_qty="10")
    session.add_all([line, foreign_line])
    await session.commit()
    receipt_id, line_id, foreign_id = receipt.id, line.id, foreign_line.id
    revision = (await api.get(f"/wms/receipts/{receipt_id}")).json()["qc_revision"]
    invalid = [{"line_id": line_id, "accepted_qty": value} for value in ["-1", "NaN", "Infinity", "0.001", "1000000000000", True]]
    invalid.append({"line_id": line_id})
    for decision in invalid:
        response = await api.post(f"/wms/receipts/{receipt_id}/qc", json={"decisions": [decision], "expected_revision": revision})
        assert response.status_code == 422, response.text
    valid = {"line_id": line_id, "accepted_qty": "7.50", "rejected_qty": "2.50"}
    for decisions in [[valid, {**valid, "line_id": foreign_id}], [valid, valid]]:
        response = await api.post(f"/wms/receipts/{receipt_id}/qc", json={"decisions": decisions, "expected_revision": revision})
        assert response.status_code == 422, response.text
    await session.refresh(line)
    assert line.accepted_qty is None
    response = await api.post(f"/wms/receipts/{receipt_id}/qc", json={"decisions": [valid], "expected_revision": revision})
    assert response.status_code == 200, response.text
    await session.refresh(line)
    assert line.accepted_qty == Decimal("7.50") and line.rejected_qty == Decimal("2.50")
    stale = await api.post(f"/wms/receipts/{receipt_id}/qc", json={"decisions": [{**valid, "accepted_qty": "1"}], "expected_revision": revision})
    assert stale.status_code == 409, stale.text
    await session.refresh(line)
    assert line.accepted_qty == Decimal("7.50")


async def test_task_list_filters_owner_before_kind_status_and_assignee(api, session):
    org = await book(api)
    response = await api.post("/accounting/organizations", headers={"X-User": "foreign-task-user"}, json={"name": "Other synthetic book", "unp": "999999991"})
    assert response.status_code == 201, response.text
    foreign = response.json()["id"]
    rows = [Task(organization_id=value, kind="putaway", status="open", sku_code="A", qty="1", assignee="Worker") for value in [org, foreign, None]]
    session.add_all(rows)
    await session.commit()
    response = await api.get("/wms/tasks", params={"kind": "putaway", "status": "open", "assignee": "Worker"})
    assert response.status_code == 200, response.text
    assert [row["id"] for row in response.json()] == [rows[0].id]
    assert (await api.get("/wms/tasks", params={"organization_id": foreign})).status_code == 403
    assert (await api.get("/wms/tasks", headers={"X-User": "no-task-grants"})).json() == []


@pytest.mark.parametrize("kind", ["tasks"])
async def test_manual_wms_task_requires_explicit_accessible_owner_and_exact_quantity(api, session, kind):
    org = await book(api)
    data = {"kind": "pick", "sku_code": "A", "qty": "1.25"}
    assert (await api.post(f"/wms/{kind}", json=data)).status_code == 422
    for invalid_owner in [None, True, "1", 0, -1]:
        assert (await api.post(f"/wms/{kind}", json={**data, "organization_id": invalid_owner})).status_code == 422
    owned = {**data, "organization_id": org}
    assert (await api.post(f"/wms/{kind}", json=owned, headers={"X-User": "foreign-manual-user"})).status_code == 403
    assert await session.scalar(select(Task.id)) is None
    for invalid_qty in ["0", "-1", "0.001", "NaN", "1000000000000"]:
        invalid = {**owned, "qty": invalid_qty}
        assert (await api.post(f"/wms/{kind}", json=invalid)).status_code == 422
    result = await api.post(f"/wms/{kind}", json=owned)
    assert result.status_code == 201, result.text
    assert result.json()["organization_id"] == org
    listed = await api.get(f"/wms/{kind}")
    assert [row["id"] for row in listed.json()] == [result.json()["id"]]
    row = await session.get(Task, result.json()["id"])
    assert row.qty == Decimal("1.25")


async def test_supplier_receipt_shortcuts_are_rejected_before_stock_changes(api, session):
    org = await book(api)
    primary_message = "Supplier receipts are created in Procurement"
    direct = await api.post("/wms/receipt", json={"organization_id": org, "sku_code": "A", "qty": "1", "warehouse": "Shared"})
    generic = await api.post("/wms/movements", json={"organization_id": org, "sku_code": "A", "qty": "1",
        "warehouse": "Shared", "kind": "in", "reason": "receipt"})
    document = await api.post("/wms/receipts", json={"organization_id": org, "warehouse": "Shared",
        "lines": [{"sku_code": "A", "expected_qty": "1"}]})
    assert [direct.status_code, generic.status_code, document.status_code] == [409, 409, 409]
    assert all(primary_message in response.text for response in [direct, generic])
    assert "Create the supplier primary receipt in Procurement" in document.text
    assert await session.scalar(select(StockMovement.id)) is None
    assert await session.scalar(select(Receipt.id)) is None


@pytest.mark.parametrize("operation", ["movements", "shipment", "transfer", "adjustment", "pack"])
async def test_manual_movement_owner_and_list_visibility(api, session, operation):
    org = await book(api)
    payload = {"sku_code": "OWN-SKU", "qty": "1.25", "warehouse": "Shared"}
    if operation == "transfer":
        location = Location(warehouse="Shared", code="DEST", title="Synthetic")
        session.add(location)
        await session.commit()
        payload["to_location_id"] = location.id
    assert (await api.post(f"/wms/{operation}", json=payload)).status_code == 422
    payload["organization_id"] = org
    assert (await api.post(f"/wms/{operation}", json=payload, headers={"X-User": "foreign-writer"})).status_code == 403
    assert await session.scalar(select(StockMovement.id)) is None
    if operation == "shipment":
        assert (await api.post("/wms/shipment", json=payload)).status_code == 409
        assert await session.scalar(select(StockMovement.id)) is None
        assert (await api.post("/wms/adjustment", json=payload)).status_code == 201
    response = await api.post(f"/wms/{operation}", json=payload)
    assert response.status_code == 201, response.text
    created = response.json() if isinstance(response.json(), list) else [response.json()]
    assert all(row["organization_id"] == org for row in created)
    session.add(StockMovement(sku_code="OWN-SKU", warehouse="Shared", kind="in", qty="1"))
    await session.commit()
    listed = await api.get("/wms/movements", params={"organization_id": org, "limit": 1})
    assert listed.status_code == 200, listed.text
    assert listed.json()[0]["id"] in [row["id"] for row in created]
    assert (await api.get("/wms/movements", headers={"X-User": "foreign-writer"})).json() == []
    assert (await api.get("/wms/movements", params={"organization_id": org}, headers={"X-User": "foreign-writer"})).status_code == 403


async def test_balance_groups_accessible_books_separately_and_excludes_unknown(api, session):
    first = await book(api)
    response = await api.post("/accounting/organizations", json={"name": "Second owned", "unp": "999999980"})
    assert response.status_code == 201, response.text
    second = response.json()["id"]
    response = await api.post("/accounting/organizations", headers={"X-User": "foreign-stock"}, json={"name": "Foreign", "unp": "999999981"})
    assert response.status_code == 201, response.text
    foreign = response.json()["id"]
    for owner, kind, qty in [(first, "in", "5.25"), (first, "out", "1"), (second, "in", "2.50"), (foreign, "in", "200"), (None, "in", "100")]:
        session.add(StockMovement(organization_id=owner, sku_code="SAME", warehouse="Shared", batch_ref="B", kind=kind, qty=qty))
    await session.commit()
    response = await api.get("/wms/balances", params={"sku": "SAME", "warehouse": "Shared"})
    assert response.status_code == 200, response.text
    rows = response.json()["rows"]
    assert {row["organization_id"]: row["qty"] for row in rows} == {first: 4.25, second: 2.5}
    assert response.json()["sku_count"] == 1
    scoped = await api.get("/wms/balances", params={"organization_id": first})
    assert [row["organization_id"] for row in scoped.json()["rows"]] == [first]
    assert (await api.get("/wms/balances", params={"organization_id": foreign})).status_code == 403
    assert (await api.get("/wms/balances", headers={"X-User": "no-stock-grants"})).json() == {"rows": [], "sku_count": 0}


@pytest.mark.parametrize("operation", ["movements", "shipment", "transfer", "adjustment", "pack"])
async def test_manual_movement_rejects_wrong_inactive_and_missing_locations(api, session, operation):
    org = await book(api)
    own = Location(warehouse="Own", code="GOOD", is_active=True)
    other = Location(warehouse="Other", code="WRONG", is_active=True)
    inactive = Location(warehouse="Own", code="INACTIVE", is_active=False)
    session.add_all([own, other, inactive])
    await session.commit()
    payload = {"organization_id": org, "sku_code": "A", "qty": "1.25", "warehouse": "Own"}
    field = "to_location_id" if operation == "transfer" else "location_id"
    for bad in [other.id, inactive.id, 999999]:
        response = await api.post(f"/wms/{operation}", json={**payload, field: bad})
        assert response.status_code == 422, response.text
        assert await session.scalar(select(StockMovement.id)) is None
    if operation == "transfer":
        response = await api.post("/wms/transfer", json={**payload, "from_location_id": other.id, "to_location_id": own.id})
        assert response.status_code == 422, response.text
        assert await session.scalar(select(StockMovement.id)) is None
    if operation == "shipment":
        assert (await api.post("/wms/shipment", json={**payload, field: own.id})).status_code == 409
        assert await session.scalar(select(StockMovement.id)) is None
        assert (await api.post("/wms/adjustment", json={**payload, field: own.id})).status_code == 201
    response = await api.post(f"/wms/{operation}", json={**payload, field: own.id})
    assert response.status_code == 201, response.text


async def test_receipt_checks_qc_location_and_rechecks_all_before_accept(api, session):
    from modules.wms.models import ReceiptLine

    org = await book(api)
    good = Location(warehouse="Own", code="GOOD", is_active=True)
    bad = Location(warehouse="Other", code="BAD", is_active=True)
    session.add_all([good, bad])
    doc = Receipt(organization_id=org, warehouse="Own", status="pending_qc")
    session.add(doc)
    await session.flush()
    first = ReceiptLine(receipt_id=doc.id, sku_code="A", expected_qty="1.25")
    second = ReceiptLine(receipt_id=doc.id, sku_code="B", expected_qty="2")
    session.add_all([first, second])
    await session.commit()
    revision = (await api.get(f"/wms/receipts/{doc.id}")).json()["qc_revision"]
    decisions = [{"line_id": first.id, "accepted_qty": "1.25", "location_id": good.id}, {"line_id": second.id, "accepted_qty": "2", "location_id": bad.id}]
    response = await api.post(f"/wms/receipts/{doc.id}/qc", json={"expected_revision": revision, "decisions": decisions})
    assert response.status_code == 422, response.text
    await session.refresh(first)
    assert first.accepted_qty is None
    decisions[1]["location_id"] = good.id
    response = await api.post(f"/wms/receipts/{doc.id}/qc", json={"expected_revision": revision, "decisions": decisions})
    assert response.status_code == 200, response.text
    good.is_active = False
    await session.commit()
    response = await api.post(f"/wms/receipts/{doc.id}/accept")
    assert response.status_code == 422, response.text
    assert await session.scalar(select(StockMovement.id)) is None
    assert await session.scalar(select(Task.id)) is None
    await session.refresh(doc)
    assert doc.status == "pending_qc"
    good.is_active = True
    await session.commit()
    assert (await api.post(f"/wms/receipts/{doc.id}/accept")).status_code == 200
    assert len((await session.scalars(select(StockMovement))).all()) == 2


@pytest.mark.parametrize("kind", ["putaway", "pick"])
async def test_task_location_rechecked_before_completion_and_cancel_remains_available(api, session, kind):
    org = await book(api)
    good = Location(warehouse="Own", code="GOOD", is_active=True)
    bad = Location(warehouse="Other", code="BAD", is_active=True)
    session.add_all([good, bad])
    await session.commit()
    payload = {"organization_id": org, "kind": kind, "sku_code": "A", "qty": "1.25", "warehouse": "Own", "from_location_id": bad.id}
    assert (await api.post("/wms/tasks", json=payload)).status_code == 422
    payload.update(from_location_id=good.id, to_location_id=good.id)
    response = await api.post("/wms/tasks", json=payload)
    assert response.status_code == 201, response.text
    task_id = response.json()["id"]
    good.is_active = False
    await session.commit()
    response = await api.patch(f"/wms/tasks/{task_id}", json={"status": "done", "assignee": "Must not persist"})
    assert response.status_code == 422, response.text
    assert await session.scalar(select(StockMovement.id)) is None
    task = await session.get(Task, task_id, populate_existing=True)
    assert task.status == "open" and task.assignee != "Must not persist"
    response = await api.patch(f"/wms/tasks/{task_id}", json={"status": "canceled"})
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("event_type", ["sales.stock.reserved", "sales.stock.released"])
async def test_stock_event_without_context_stays_pending_and_can_retry(session, event_type):
    from core.domain.models import OutboxEvent
    from core.services.eventbus import OutboxEventBus
    from modules.wms.events import on_stock_released, on_stock_reserved

    bus = OutboxEventBus()
    bus.subscribe(event_type, on_stock_reserved if event_type.endswith("reserved") else on_stock_released)
    await invoice(session, 1, [{"sku_code": "A", "qty": "1.25"}], released=event_type.endswith("released"))
    bus.emit(session, event_type, {"document_id": 1, "items": [{"sku_code": "A", "warehouse": "Synthetic", "qty": "1.25"}]})
    await session.commit()
    with pytest.raises(ValueError, match="EventContext is required"):
        await bus.relay_once(session)
    await session.rollback()
    event = await session.scalar(select(OutboxEvent))
    assert event.processed_at is None
    assert await session.scalar(select(StockMovement.id)) is None
    assert await session.scalar(select(Task.id)) is None
    assert await bus.relay_once(session, event_context(session)) == 1
    movements = (await session.scalars(select(StockMovement))).all()
    assert movements == []


@pytest.mark.parametrize("released", [False, True])
@pytest.mark.parametrize("invalid", [None, True, "NaN", "Infinity", "0", "-1", "0.001", "1000000000000"])
async def test_reservation_batch_rejects_bad_second_quantity_before_any_add(session, released, invalid):
    from modules.wms.events import on_stock_released, on_stock_reserved

    handler = on_stock_released if released else on_stock_reserved
    with pytest.raises(ValueError, match="quantity"):
        await handler({"items": [{"sku_code": "A", "qty": "1.25"}, {"sku_code": "B", "qty": invalid}]}, SimpleNamespace(session=session))
    assert not session.new
    assert await session.scalar(select(StockMovement.id)) is None
    assert await session.scalar(select(Task.id)) is None


@pytest.mark.parametrize("items", [None, {}, [None], [{"sku_code": "", "qty": "1"}], [{"sku_code": "A", "qty": "1", "warehouse": " "}]])
async def test_reservation_batch_rejects_malformed_structure(session, items):
    from modules.wms.events import on_stock_reserved

    with pytest.raises(ValueError):
        await on_stock_reserved({"items": items}, SimpleNamespace(session=session))
    assert not session.new


async def test_invoice_reservation_release_only_cancels_its_open_picks(session):
    from modules.wms.events import on_stock_released, on_stock_reserved

    items = [{"sku_code": "A", "warehouse": "W", "qty": "2"}]
    ctx = event_context(session)
    docs = {}
    for document_id in (1, 2):
        docs[document_id] = await invoice(session, document_id, items)
        await on_stock_reserved({"document_id": document_id, "items": items}, ctx)
    await session.flush()
    assert await session.scalar(select(StockMovement.id)) is None
    docs[1].reserve_status = "released"
    await session.flush()
    await on_stock_released({"document_id": 1, "items": items}, ctx)
    await session.flush()
    tasks = (await session.scalars(select(Task).order_by(Task.id))).all()
    assert [(task.doc_ref, task.status) for task in tasks] == [("sales:document:1", "canceled"), ("sales:document:2", "open")]
    assert await session.scalar(select(StockMovement.id)) is None
    tasks[1].status = "in_progress"
    docs[2].reserve_status = "released"
    await session.flush()
    with pytest.raises(ValueError, match="picking already started"):
        await on_stock_released({"document_id": 2, "items": items}, ctx)
    assert tasks[1].status == "in_progress"
    with pytest.raises(ValueError, match="document_id"):
        await on_stock_reserved({"items": items}, ctx)


async def test_out_of_order_invoice_release_and_manual_reference_are_safe(session):
    from core.services.eventbus import OutboxEventBus
    from modules.wms.events import on_stock_released, on_stock_reserved

    items = [{"sku_code": "A", "warehouse": "W", "qty": "2"}]
    manual = Task(organization_id=888, kind="pick", sku_code="UNRELATED", qty=1, warehouse="Other", doc_ref="sales:document:1", status="open")
    await invoice(session, 1, items, released=True)
    session.add(manual)
    bus = OutboxEventBus()
    bus.subscribe("sales.stock.released", on_stock_released)
    bus.subscribe("sales.stock.reserved", on_stock_reserved)
    bus.emit(session, "sales.stock.released", {"document_id": 1, "items": items})
    bus.emit(session, "sales.stock.reserved", {"document_id": 1, "items": items})
    await session.commit()
    await bus.relay_once(session, event_context(session))
    await session.commit()
    tasks = (await session.scalars(select(Task))).all()
    assert len(tasks) == 1 and tasks[0].status == "open" and tasks[0].sku_code == "UNRELATED"
    assert await session.scalar(select(StockMovement.id)) is None


@pytest.mark.parametrize("changes, error", [
    ({"organization_id": 999}, "organization differs"),
    ({"organization_id": True}, "organization differs"),
    ({"items": [{"sku_code": "A", "qty": "3", "warehouse": "W"}]}, "quantities differ"),
    ({"items": [{"sku_code": "B", "qty": "2", "warehouse": "W"}]}, "quantities differ"),
])
async def test_invoice_event_cannot_override_source_facts(session, changes, error):
    from modules.wms.events import on_stock_reserved

    items = [{"sku_code": "A", "qty": "2", "warehouse": "W"}]
    await invoice(session, 1, items)
    with pytest.raises(ValueError, match=error):
        await on_stock_reserved({"document_id": 1, "items": items, **changes}, event_context(session))
    assert await session.scalar(select(Task.id)) is None
    assert await session.scalar(select(StockMovement.id)) is None


async def test_release_requires_source_transition_and_delayed_reserve_stays_released(session):
    from modules.wms.events import on_stock_released, on_stock_reserved

    items = [{"sku_code": "A", "qty": "2", "warehouse": "W"}]
    doc = await invoice(session, 1, items)
    payload = {"document_id": 1, "items": items}
    with pytest.raises(ValueError, match="has not released"):
        await on_stock_released(payload, event_context(session))
    doc.reserve_status = "released"
    await session.flush()
    await on_stock_reserved(payload, event_context(session))
    assert await session.scalar(select(Task.id)) is None
    assert await session.scalar(select(StockMovement.id)) is None


async def test_release_reloads_pick_state_before_cancelling(session):
    from sqlalchemy import update

    from modules.wms.events import on_stock_released, on_stock_reserved

    items = [{"sku_code": "A", "qty": "2", "warehouse": "W"}]
    doc = await invoice(session, 1, items)
    payload = {"document_id": 1, "items": items}
    await on_stock_reserved(payload, event_context(session))
    task = await session.scalar(select(Task))
    await session.execute(update(Task).where(Task.id == task.id).values(status="done")
                          .execution_options(synchronize_session=False))
    assert task.status == "open"  # Previously loaded identity map is deliberately stale.
    doc.reserve_status = "released"
    await session.flush()
    with pytest.raises(ValueError, match="picking already started"):
        await on_stock_released(payload, event_context(session))
    assert task.status == "done"
    assert await session.scalar(select(Task.status).where(Task.id == task.id)) == "done"


async def test_reservation_versions_do_not_change_physical_stock_and_replay_safely(api, session):
    from core.domain.models import OutboxEvent
    from modules.wms.models import ReservationVersion

    org = await book(api)
    payload = {"organization_id": org, "source": "sales_document:synthetic:line:1", "version": 1, "sku_code": "A", "warehouse": "Own", "qty": "3.25", "evidence": "Confirmed synthetic reservation"}
    assert (await api.post("/wms/reservations", json=payload, headers={"X-User": "foreign"})).status_code == 403
    first = await api.post("/wms/reservations", json=payload)
    assert first.status_code == 201, first.text
    replay = await api.post("/wms/reservations", json=payload)
    assert replay.status_code == 201 and replay.json()["id"] == first.json()["id"]
    assert (await api.post("/wms/reservations", json={**payload, "qty": "4"})).status_code == 409
    assert (await api.post("/wms/reservations", json={**payload, "version": 3})).status_code == 409
    assert (await api.post("/wms/reservations", json={**payload, "version": 2, "warehouse": "Other"})).status_code == 409
    partial = await api.post("/wms/reservations", json={**payload, "version": 2, "qty": "1.25"})
    assert partial.status_code == 201, partial.text
    release = await api.post("/wms/reservations", json={**payload, "version": 3, "qty": "0"})
    assert release.status_code == 201, release.text
    assert (await api.post("/wms/reservations", json=payload)).json()["id"] == first.json()["id"]
    latest = await api.get("/wms/reservations", params={"organization_id": org})
    assert latest.status_code == 200 and latest.json()[0]["qty"] == "0.00"
    assert (await api.get("/wms/reservations", params={"organization_id": org}, headers={"X-User": "foreign"})).status_code == 403
    history = await api.get("/wms/reservations/history", params={"organization_id": org, "source": payload["source"]})
    assert [row["qty"] for row in history.json()] == ["3.25", "1.25", "0.00"]
    assert (await api.get("/wms/reservations/history", params={"organization_id": org, "source": payload["source"]}, headers={"X-User": "foreign"})).status_code == 403
    assert len((await session.scalars(select(ReservationVersion))).all()) == 3
    events = (await session.scalars(select(OutboxEvent).where(OutboxEvent.event_type == "wms.reservation.recorded"))).all()
    assert len(events) == 3
    assert await session.scalar(select(StockMovement.id)) is None
    assert await session.scalar(select(Task.id)) is None


async def test_reservation_summary_uses_only_latest_versions_and_selected_book(api, session):
    org = await book(api)
    base = {"organization_id": org, "sku_code": "A", "warehouse": "Own", "evidence": "Synthetic summary"}
    for source, version, qty, warehouse in [("one", 1, "10", "Own"), ("one", 2, "1.25", "Own"), ("two", 1, "2.50", "Own"), ("released", 1, "99", "Own"), ("released", 2, "0", "Own"), ("other-cell", 1, "4", "Other")]:
        response = await api.post("/wms/reservations", json={**base, "source": source, "version": version, "qty": qty, "warehouse": warehouse})
        assert response.status_code == 201, response.text
    foreign = await api.post("/accounting/organizations", headers={"X-User": "foreign-summary"}, json={"name": "Other book", "unp": "999999979"})
    foreign_id = foreign.json()["id"]
    assert (await api.post("/wms/reservations", headers={"X-User": "foreign-summary"}, json={**base, "organization_id": foreign_id, "source": "one", "version": 1, "qty": "999"})).status_code == 201
    response = await api.get("/wms/reservations/summary", params={"organization_id": org})
    assert response.status_code == 200, response.text
    assert response.json() == [
        {"organization_id": org, "sku_code": "A", "warehouse": "Other", "qty": "4.00", "source_count": 1},
        {"organization_id": org, "sku_code": "A", "warehouse": "Own", "qty": "3.75", "source_count": 2},
    ]
    assert (await api.get("/wms/reservations/summary", params={"organization_id": foreign_id})).status_code == 403
    latest = await api.get("/wms/reservations", params={"organization_id": org})
    assert len(latest.json()) == 4
