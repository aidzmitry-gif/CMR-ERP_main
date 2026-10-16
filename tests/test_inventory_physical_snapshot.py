"""Real company-scoped physical movements: snapshot provenance, freshness and rollback."""
from decimal import Decimal

import pytest
from sqlalchemy import event, select

from modules.wms.models import CycleCountPlan, InventoryCount, InventoryLine, StockMovement
from tests.test_inventory_organization import CONFIRM, count, ready_line
from tests.test_inventory_organization import books as _books_fixture

# Expose the shared fixture without importing a name shadowed by test parameters.
books = _books_fixture


@pytest.mark.parametrize("field,value", [
    ("expected_source", None), ("expected_source", "onec"),
    ("journal_complete", False), ("journal_complete", 1),
    ("source_evidence", "   "), ("source_evidence", None),
])
async def test_source_must_be_explicit_and_confirmed(api, session, books, field, value):
    payload = {**CONFIRM, "organization_id": books[0], field: value}
    for kind in ["inventory", "cycle-plans"]:
        response = await api.post(f"/wms/{kind}", json=payload)
        assert response.status_code == 422, response.text
    assert await session.scalar(select(InventoryCount.id)) is None
    assert await session.scalar(select(CycleCountPlan.id)) is None


async def test_snapshot_is_scoped_to_book_and_warehouse_and_ignores_reservations(api, session, books):
    rows = [
        StockMovement(organization_id=books[0], warehouse="Shared", sku_code="A", kind="in", qty=30, reason="receipt"),
        StockMovement(organization_id=books[1], warehouse="Shared", sku_code="A", kind="in", qty=900, reason="receipt"),
        StockMovement(organization_id=None, warehouse="Shared", sku_code="A", kind="in", qty=700, reason="receipt"),
        StockMovement(organization_id=books[0], warehouse="Other", sku_code="A", kind="in", qty=500, reason="receipt"),
        StockMovement(organization_id=books[0], warehouse="Shared", sku_code="A", kind="out", qty=10, reason="reserve"),
        StockMovement(organization_id=books[0], warehouse="Shared", sku_code="A", kind="in", qty=10, reason="release"),
    ]
    session.add_all(rows)
    await session.commit()
    cutoff = rows[0].id
    doc_id = await count(api, books[0])
    # The explicit source must work even with no global StockGateway.
    api._transport.app.state.core.services.stock = None
    response = await api.post(f"/wms/inventory/{doc_id}/populate")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["expected_source"] == "wms_physical"
    assert data["source_evidence"] == CONFIRM["source_evidence"]
    assert data["journal_confirmed_by"] == "inventory-owner"
    assert data["journal_confirmed_at"] and data["snapshot_at"]
    assert data["snapshot_cutoff"] == cutoff and len(data["snapshot_version"]) == 64
    assert len(data["lines"]) == 1 and data["lines"][0]["expected_qty"] == 30
    assert data["lines"][0]["unit_cost"] is None
    again = (await api.post(f"/wms/inventory/{doc_id}/populate")).json()
    assert again == data


async def test_known_net_zero_is_distinct_from_unknown(api, session, books):
    session.add_all([
        StockMovement(organization_id=books[0], warehouse="Shared", sku_code="ZERO", kind="in", qty=3, reason="receipt"),
        StockMovement(organization_id=books[0], warehouse="Shared", sku_code="ZERO", kind="out", qty=3, reason="shipment"),
        StockMovement(organization_id=books[1], warehouse="Shared", sku_code="FOREIGN", kind="in", qty=5, reason="receipt"),
        StockMovement(organization_id=books[0], warehouse="Shared", sku_code="RESERVED", kind="out", qty=8, reason="reserve"),
    ])
    await session.commit()
    doc_id = await count(api, books[0])
    for sku in ["UNKNOWN", "FOREIGN", "RESERVED"]:
        result = await api.post(f"/wms/inventory/{doc_id}/lines", json={"sku_code": sku, "counted_qty": 3})
        assert result.status_code == 409, result.text
    assert await session.scalar(select(InventoryLine.id)) is None
    doc = await session.get(InventoryCount, doc_id)
    assert doc.snapshot_version is None  # failed unknown lookup cannot pin a snapshot
    known = await api.post(f"/wms/inventory/{doc_id}/lines", json={"sku_code": "ZERO", "counted_qty": 0})
    assert known.status_code == 201 and known.json()["expected_qty"] == 0
    assert (await api.post(f"/wms/inventory/{doc_id}/lines", json={"sku_code": "ZERO"})).status_code == 409
    done = await api.post(f"/wms/inventory/{doc_id}/complete")
    assert done.status_code == 200, done.text
    detail = (await api.get(f"/wms/inventory/{doc_id}")).json()
    assert all(detail["summary"][field] is None for field in ["shortage_value", "surplus_value", "net_value"])
    assert await session.scalar(select(StockMovement.id).where(StockMovement.reason == "adjustment")) is None


@pytest.mark.parametrize("change", ["receipt", "shipment", "edit_existing", "delete_existing", "net_zero_transfer"])
async def test_stale_snapshot_cannot_adjust_changed_ledger(api, session, books, change):
    doc_id = await count(api, books[0])
    await ready_line(api, session, doc_id)
    original = (await api.get(f"/wms/inventory/{doc_id}")).json()
    if change in {"receipt", "shipment"}:
        response = await api.post(f"/wms/{change}", json={"organization_id": books[0], "warehouse": "Shared", "sku_code": "A", "qty": 1})
        assert response.status_code == 201
    elif change == "net_zero_transfer":
        session.add_all([StockMovement(organization_id=books[0], warehouse="Shared", sku_code="A", kind=kind, qty=2, reason="transfer") for kind in ["in", "out"]])
        await session.commit()
    else:
        movement = await session.scalar(select(StockMovement))
        if change == "edit_existing":
            movement.qty = Decimal("31")
        else:
            await session.delete(movement)
        await session.commit()
    response = await api.post(f"/wms/inventory/{doc_id}/complete")
    assert response.status_code == 409, response.text
    assert (await api.post(f"/wms/inventory/{doc_id}/populate")).status_code == 409
    current = (await api.get(f"/wms/inventory/{doc_id}")).json()
    assert current["status"] == "open" and current["snapshot_version"] == original["snapshot_version"]
    assert current["snapshot_cutoff"] == original["snapshot_cutoff"]
    assert current["lines"][0]["expected_qty"] == 30
    assert await session.scalar(select(StockMovement.id).where(StockMovement.reason == "adjustment")) is None


async def test_irrelevant_foreign_and_reservation_changes_do_not_stale_snapshot(api, session, books):
    doc_id = await count(api, books[0])
    await ready_line(api, session, doc_id)
    session.add_all([
        StockMovement(organization_id=books[1], warehouse="Shared", sku_code="A", kind="in", qty=999, reason="receipt"),
        StockMovement(organization_id=books[0], warehouse="Other", sku_code="A", kind="in", qty=999, reason="receipt"),
        StockMovement(organization_id=books[0], warehouse="Shared", sku_code="A", kind="out", qty=999, reason="reserve"),
    ])
    await session.commit()
    result = await api.post(f"/wms/inventory/{doc_id}/complete")
    assert result.status_code == 200, result.text
    adjustments = (await session.scalars(select(StockMovement).where(StockMovement.reason == "adjustment"))).all()
    assert len(adjustments) == 1 and adjustments[0].qty == 3 and adjustments[0].organization_id == books[0]


async def test_cycle_run_requires_fresh_user_confirmation(api, session, books):
    response = await api.post("/wms/cycle-plans", json={**CONFIRM, "organization_id": books[0], "warehouse": "Shared"})
    plan_id = response.json()["id"]
    assert (await api.post(f"/wms/cycle-plans/{plan_id}/run")).status_code == 422
    assert (await api.post(f"/wms/cycle-plans/{plan_id}/run", json={**CONFIRM, "journal_complete": False})).status_code == 422
    assert await session.scalar(select(InventoryCount.id)) is None


async def test_inventory_and_physical_writer_use_same_organization_lock(api, session, books, monkeypatch):
    from modules.accounting import gateway

    calls = []
    original = gateway.lock_organization

    async def tracked_lock(session, organization_id):
        calls.append(organization_id)
        return await original(session, organization_id)

    monkeypatch.setattr(gateway, "lock_organization", tracked_lock)
    response = await api.post("/wms/adjustment", json={"organization_id": books[0], "warehouse": "Shared", "sku_code": "A", "qty": 30})
    assert response.status_code == 201 and calls == [books[0]]
    calls.clear()
    doc_id = await count(api, books[0])
    assert calls == [books[0]]
    calls.clear()
    response = await api.post(f"/wms/inventory/{doc_id}/populate")
    assert response.status_code == 200 and calls == [books[0]]
    calls.clear()
    line_id = response.json()["lines"][0]["id"]
    assert (await api.patch(f"/wms/inventory/lines/{line_id}", json={"counted_qty": 29})).status_code == 200
    assert calls == [books[0]]
    calls.clear()
    assert (await api.post(f"/wms/inventory/{doc_id}/complete")).status_code == 200
    assert calls == [books[0]]


async def test_multiline_posting_failure_keeps_snapshot_and_all_rows_retryable(api, session, books):
    session.add_all([StockMovement(organization_id=books[0], warehouse="Shared", sku_code=sku, kind="in", qty=30, reason="receipt") for sku in ["A", "B"]])
    await session.commit()
    doc_id = await count(api, books[0])
    snapshot = (await api.post(f"/wms/inventory/{doc_id}/populate")).json()
    for line in snapshot["lines"]:
        assert (await api.patch(f"/wms/inventory/lines/{line['id']}", json={"counted_qty": 29})).status_code == 200

    def fail_second_sku(mapper, connection, target):
        if target.sku_code == "B":
            raise RuntimeError("synthetic second SKU failure")

    event.listen(StockMovement, "before_insert", fail_second_sku)
    try:
        with pytest.raises(RuntimeError, match="second SKU"):
            await api.post(f"/wms/inventory/{doc_id}/complete")
    finally:
        event.remove(StockMovement, "before_insert", fail_second_sku)
    result = (await api.get(f"/wms/inventory/{doc_id}")).json()
    assert result["status"] == "open" and result["snapshot_version"] == snapshot["snapshot_version"]
    assert await session.scalar(select(StockMovement.id).where(StockMovement.reason == "adjustment")) is None
    assert (await api.post(f"/wms/inventory/{doc_id}/complete")).status_code == 200
    adjustments = (await session.scalars(select(StockMovement).where(StockMovement.reason == "adjustment"))).all()
    assert len(adjustments) == 2 and all(row.qty == 1 and row.organization_id == books[0] for row in adjustments)
