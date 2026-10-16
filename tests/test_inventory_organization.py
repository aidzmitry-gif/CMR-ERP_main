"""Company ownership, fail-closed source access and atomic inventory posting."""
from decimal import Decimal
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import event, select

from modules.wms.models import CycleCountPlan, InventoryCount, InventoryLine, StockMovement

CONFIRM = {"expected_source": "wms_physical", "source_evidence": "Test physical ledger completeness verified", "journal_complete": True}


@pytest_asyncio.fixture
async def books(api):
    result = []
    for actor, unp in [("inventory-owner", "999999981"), ("foreign-owner", "999999982")]:
        response = await api.post("/accounting/organizations", headers={"X-User": actor},
                                  json={"name": actor, "unp": unp})
        assert response.status_code == 201, response.text
        result.append(response.json()["id"])
    api.headers["X-User"] = "inventory-owner"
    return result


async def count(api, org):
    response = await api.post("/wms/inventory", json={**CONFIRM, "organization_id": org, "warehouse": "Shared"})
    assert response.status_code == 201, response.text
    assert response.json()["organization_id"] == org
    return response.json()["id"]


async def ready_line(api, session, count_id):
    doc = await session.get(InventoryCount, count_id)
    assert doc.organization_id is not None
    # Seed actual physical ledger rows. Only API populate may create owned snapshots.
    session.add(StockMovement(organization_id=doc.organization_id, sku_code="A", warehouse="Shared", kind="in", qty=Decimal("30"), reason="receipt"))
    await session.commit()
    response = await api.post(f"/wms/inventory/{count_id}/populate")
    assert response.status_code == 200, response.text
    line_id = response.json()["lines"][0]["id"]
    response = await api.patch(f"/wms/inventory/lines/{line_id}", json={"counted_qty": 27})
    assert response.status_code == 200, response.text
    return line_id


@pytest.mark.parametrize("kind", ["inventory", "cycle-plans"])
@pytest.mark.parametrize("owner", [None, True, "1", 0, -1])
async def test_inventory_creation_requires_exact_owner(api, session, books, kind, owner):
    payload = {"warehouse": "Shared"}
    if owner is not None:
        payload["organization_id"] = owner
    response = await api.post(f"/wms/{kind}", json=payload)
    assert response.status_code == 422, response.text
    assert await session.scalar(select(InventoryCount.id)) is None
    assert await session.scalar(select(CycleCountPlan.id)) is None


@pytest.mark.parametrize("kind", ["inventory", "cycle-plans"])
async def test_inventory_creation_cannot_borrow_foreign_book(api, session, books, kind):
    response = await api.post(f"/wms/{kind}", json={**CONFIRM, "organization_id": books[1]})
    assert response.status_code == 403, response.text
    assert await session.scalar(select(InventoryCount.id)) is None
    assert await session.scalar(select(CycleCountPlan.id)) is None


async def test_inventory_reads_and_all_mutations_recheck_owner(api, session, books):
    own = await count(api, books[0])
    foreign = InventoryCount(organization_id=books[1], warehouse="Shared")
    legacy = InventoryCount(warehouse="Shared")
    session.add_all([foreign, legacy])
    await session.commit()
    foreign_id, legacy_id = foreign.id, legacy.id
    own_line = await ready_line(api, session, own)
    lines = [InventoryLine(count_id=i, sku_code="A", expected_qty=30, counted_qty=27) for i in [foreign_id, legacy_id]]
    session.add_all(lines)
    await session.commit()
    foreign_line, legacy_line = [line.id for line in lines]
    listed = await api.get("/wms/inventory")
    assert listed.status_code == 200
    assert [row["id"] for row in listed.json()] == [own]
    assert (await api.get("/wms/inventory", params={"organization_id": books[1]})).status_code == 403
    for doc_id, line_id, code in [(foreign_id, foreign_line, 403), (legacy_id, legacy_line, 409)]:
        assert (await api.get(f"/wms/inventory/{doc_id}")).status_code == code
        for action in ["populate", "complete"]:
            assert (await api.post(f"/wms/inventory/{doc_id}/{action}")).status_code == code
        assert (await api.post(f"/wms/inventory/{doc_id}/lines", json={"sku_code": "X"})).status_code == code
        assert (await api.patch(f"/wms/inventory/lines/{line_id}", json={"counted_qty": 1})).status_code == code
        await session.refresh(foreign if doc_id == foreign_id else legacy)
        assert (await session.get(InventoryCount, doc_id)).status == "open"
        assert (await session.get(InventoryLine, line_id)).counted_qty == Decimal("27")
    # Cannot inject a different book into update payloads to re-home an owned line.
    assert (await api.patch(f"/wms/inventory/lines/{own_line}", json={
        "organization_id": books[1], "counted_qty": 1})).status_code == 422
    assert await session.scalar(select(StockMovement.id).where(StockMovement.reason == "adjustment")) is None


async def test_cycle_reads_and_mutations_exclude_foreign_and_legacy(api, session, books):
    response = await api.post("/wms/cycle-plans", json={**CONFIRM, "organization_id": books[0], "warehouse": "Shared"})
    assert response.status_code == 201
    own_id = response.json()["id"]
    rows = [CycleCountPlan(organization_id=org, warehouse="Shared") for org in [books[1], None]]
    session.add_all(rows)
    await session.commit()
    assert [r["id"] for r in (await api.get("/wms/cycle-plans")).json()] == [own_id]
    assert (await api.get("/wms/cycle-plans", params={"organization_id": books[1]})).status_code == 403
    for row, status in zip(rows, [403, 409]):
        assert (await api.patch(f"/wms/cycle-plans/{row.id}", json={"cadence_days": 3})).status_code == status
        assert (await api.post(f"/wms/cycle-plans/{row.id}/run", json=CONFIRM)).status_code == status
    assert (await api.patch(f"/wms/cycle-plans/{own_id}", json={**CONFIRM, "organization_id": books[1]})).status_code == 422
    changed = await api.patch(f"/wms/cycle-plans/{own_id}", json={"cadence_days": 7})
    assert changed.status_code == 200 and changed.json()["organization_id"] == books[0]
    assert await session.scalar(select(InventoryCount.id)) is None


@pytest.mark.parametrize("facade", [None, SimpleNamespace(), SimpleNamespace(source_member=None)])
async def test_missing_accounting_facade_methods_fail_closed(api, session, books, facade):
    doc_id = await count(api, books[0])
    api._transport.app.state.core.services.accounting = facade
    for endpoint in ["/wms/inventory", f"/wms/inventory/{doc_id}", "/wms/cycle-plans"]:
        response = await api.get(endpoint)
        assert response.status_code == 503, response.text
    assert (await api.post("/wms/inventory", json={**CONFIRM, "organization_id": books[0]})).status_code == 503
    assert (await api.post(f"/wms/inventory/{doc_id}/complete")).status_code == 503
    assert await session.scalar(select(StockMovement.id)) is None


async def test_absent_owned_physical_source_never_becomes_expected_zero(api, session, books):
    doc_id = await count(api, books[0])
    response = await api.post(f"/wms/inventory/{doc_id}/populate")
    assert response.status_code == 409, response.text
    response = await api.post(f"/wms/inventory/{doc_id}/lines", json={"sku_code": "UNKNOWN", "counted_qty": 3})
    assert response.status_code == 409, response.text
    assert await session.scalar(select(InventoryLine.id)) is None
    assert (await api.post(f"/wms/inventory/{doc_id}/complete")).status_code == 409


async def test_complete_posts_owned_adjustment_once_and_locks_lines(api, session, books):
    doc_id = await count(api, books[0])
    line_id = await ready_line(api, session, doc_id)
    for _ in range(3):
        response = await api.post(f"/wms/inventory/{doc_id}/complete")
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "done" and response.json()["organization_id"] == books[0]
    rows = (await session.scalars(select(StockMovement).where(StockMovement.reason == "adjustment"))).all()
    assert len(rows) == 1
    movement = rows[0]
    assert (movement.organization_id, movement.kind, movement.qty, movement.reason) == (books[0], "out", Decimal("3"), "adjustment")
    assert movement.doc_ref == response.json()["number"]
    detail = (await api.get(f"/wms/inventory/{doc_id}")).json()
    assert detail["lines"][0]["unit_cost"] is None
    assert detail["summary"]["shortage_value"] is None
    assert detail["summary"]["net_value"] is None
    assert (await api.patch(f"/wms/inventory/lines/{line_id}", json={"counted_qty": 25})).status_code == 409
    assert (await api.post(f"/wms/inventory/{doc_id}/complete", headers={"X-User": "foreign-owner"})).status_code == 403


async def test_complete_uses_current_count_instead_of_cached_line(api, session, books):
    from sqlalchemy import update

    doc_id = await count(api, books[0])
    line_id = await ready_line(api, session, doc_id)
    line = await session.get(InventoryLine, line_id)
    await session.execute(update(InventoryLine).where(InventoryLine.id == line_id)
                          .values(counted_qty=25).execution_options(synchronize_session=False))
    await session.commit()
    assert line.counted_qty == 27
    response = await api.post(f"/wms/inventory/{doc_id}/complete")
    assert response.status_code == 200, response.text
    movement = await session.scalar(select(StockMovement).where(StockMovement.reason == "adjustment"))
    assert movement.kind == "out" and movement.qty == 5
    assert line.counted_qty == 25


async def test_complete_rolls_back_status_and_all_movements_on_failure(api, session, books):
    doc_id = await count(api, books[0])
    await ready_line(api, session, doc_id)

    def fail_insert(*args):
        raise RuntimeError("synthetic movement storage failure")

    event.listen(StockMovement, "before_insert", fail_insert)
    try:
        with pytest.raises(RuntimeError, match="synthetic movement"):
            await api.post(f"/wms/inventory/{doc_id}/complete")
    finally:
        event.remove(StockMovement, "before_insert", fail_insert)
    doc = await session.get(InventoryCount, doc_id)
    assert doc.status == "open" and doc.completed_at is None
    assert await session.scalar(select(StockMovement.id).where(StockMovement.reason == "adjustment")) is None
    assert (await api.post(f"/wms/inventory/{doc_id}/complete")).status_code == 200


async def test_cycle_source_failure_does_not_create_document_or_reschedule(api, session, books):
    response = await api.post("/wms/cycle-plans", json={**CONFIRM, "organization_id": books[0], "warehouse": "Shared", "next_due_date": "2020-01-01"})
    plan_id = response.json()["id"]
    response = await api.post(f"/wms/cycle-plans/{plan_id}/run", json=CONFIRM)
    assert response.status_code == 409
    assert await session.scalar(select(InventoryCount.id)) is None
    plan = await session.get(CycleCountPlan, plan_id)
    assert str(plan.next_due_date) == "2020-01-01" and plan.last_run_at is None


async def test_cycle_transfers_owner_with_actual_physical_movements(api, session, books):
    session.add(StockMovement(organization_id=books[0], sku_code="A", warehouse="Shared", kind="in", qty=Decimal("30"), reason="receipt"))
    await session.commit()
    response = await api.post("/wms/cycle-plans", json={**CONFIRM, "organization_id": books[0], "warehouse": "Shared", "next_due_date": "2020-01-01"})
    plan_id = response.json()["id"]
    response = await api.post(f"/wms/cycle-plans/{plan_id}/run", json=CONFIRM)
    assert response.status_code == 200, response.text
    assert response.json()["organization_id"] == books[0]
    assert response.json()["expected_source"] == "wms_physical"
    assert response.json()["snapshot_version"] and response.json()["snapshot_cutoff"]
    assert response.json()["lines"][0]["expected_qty"] == 30
    plan = await session.get(CycleCountPlan, plan_id)
    assert str(plan.next_due_date) > "2020-01-01" and plan.last_run_at is not None
