"""New optional-WMS behavior; existing unrelated suites are not repeated."""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from modules.sales import deal_loss  # noqa: F401 -- register source guards before fixtures
from modules.sales.reservation_source import SalesReservationSource
from modules.wms import invoice_remainder  # noqa: F401 -- register receipt links
from modules.wms.invoice_reservations import reserve
from modules.wms.invoice_shipments import ShipmentInput, create, preview
from modules.wms.models import StockMovement, Task, WarehouseDirectory
from modules.wms.reservation_events import apply
from modules.wms.warehouse_modes import frozen_modes
from tests.test_invoice_stock_allocation import setup


async def prepared(api, session, enabled):
    org, facts, allocation, actor = await setup(api, session, create_warehouse=False)
    warehouse = WarehouseDirectory(organization_id=org, name="W", title="Warehouse",
                                   created_by=actor, wms_enabled=enabled)
    session.add(warehouse)
    await session.flush()
    await reserve(session, org, facts, allocation, actor)
    facts = await SalesReservationSource().invoice_shipping_source(
        session, facts["document_id"], organization_id=org,
        expected_version=facts["version"], expected_content_sha256=facts["content_sha256"],
    )
    await apply(session, 1, [("A", "W", Decimal("2")), ("A", "W", Decimal("3"))],
                organization_id=org, release=False)
    basis = await preview(session, org, facts)
    command = ShipmentInput(
        source_key=uuid4(), expected_version=facts["version"],
        expected_content_sha256=facts["content_sha256"],
        expected_reservation_digest=basis["reservation_digest"],
        expected_remaining_digest=basis["remaining_digest"],
        expected_physical_digest=basis["physical_digest"], operation_date=date.today(),
        evidence="Synthetic source document 117, not a statutory waybill",
        lines=[{"line_no": 1, "warehouse": "W", "qty": "1.00"}],
    )
    return org, facts, actor, warehouse, basis, command


async def test_document_mode_has_no_tasks_and_replay_does_not_issue_twice(api, session):
    org, facts, actor, _, basis, command = await prepared(api, session, False)
    assert {row["execution_mode"] for row in basis["lines"]} == {"document"}
    assert await session.scalar(select(func.count()).select_from(Task)) == 0
    first = await create(session, org, facts, command, actor, execution_mode="document")
    assert first["snapshot"]["execution_mode"] == "document"
    second = await create(session, org, facts, command, actor, execution_mode="document")
    assert second == first
    issues = (await session.scalars(select(StockMovement).where(StockMovement.kind == "out"))).all()
    assert len(issues) == 1 and issues[0].qty == Decimal("1")
    with pytest.raises(HTTPException) as rejected:
        await create(session, org, facts, command, actor, execution_mode="wms")
    assert rejected.value.status_code == 409


async def test_wms_mode_creates_tasks_and_rejects_document_origin(api, session):
    org, facts, actor, _, basis, command = await prepared(api, session, True)
    assert {row["execution_mode"] for row in basis["lines"]} == {"wms"}
    assert await session.scalar(select(func.count()).select_from(Task)) == 2
    with pytest.raises(HTTPException) as rejected:
        await create(session, org, facts, command, actor, execution_mode="document")
    assert rejected.value.status_code == 409
    assert await session.scalar(select(func.count()).select_from(StockMovement).where(StockMovement.kind == "out")) == 0
    result = await create(session, org, facts, command, actor, execution_mode="wms")
    assert result["snapshot"]["execution_mode"] == "wms"


async def test_switch_rejects_outstanding_reservations(api, session):
    org, _, _, warehouse, _, _ = await prepared(api, session, False)
    warehouse_id = warehouse.id
    await session.commit()
    result = await api.patch(f"/wms/organizations/{org}/warehouses/{warehouse_id}/execution-mode",
                             json={"wms_enabled": True, "expected_wms_enabled": False})
    assert result.status_code == 409, result.text
    await session.refresh(warehouse)
    assert warehouse.wms_enabled is False


def test_frozen_modes_are_strict_and_legacy_is_explicitly_wms():
    assert frozen_modes(None, ["W"]) == {"W": True}
    assert frozen_modes({"W": False, "Other": True}, ["W", "Other"]) == {"W": False, "Other": True}
    for malformed in ({"W": "false"}, {"W": 0}, {}, {"W": False, "foreign": False}):
        with pytest.raises(ValueError):
            frozen_modes(malformed, ["W"])


@pytest.mark.parametrize("method", ["document_shipment_member", "warehouse_mode_admin"])
async def test_new_write_facades_recheck_disabled_identity_after_book_lock(monkeypatch, method):
    from modules.accounting import routes
    from modules.accounting.gateway import AccountingService

    order = []
    user = SimpleNamespace(username="operator", roles=["director"], keycloak_user_id="subject",
                           local_status="active", crm_restricted=False)

    async def membership(session, org, actor):
        order.append("locked")
        return "chief"

    async def fresh_identity(original, session):
        assert order == ["locked"]
        order.append("fresh")
        return SimpleNamespace(**{**vars(original), "local_status": "disabled"})

    monkeypatch.setattr(routes, "organization_role", membership)
    monkeypatch.setattr(routes, "resolve_effective_oidc_user", fresh_identity)
    with pytest.raises(HTTPException) as rejected:
        await getattr(AccountingService(), method)(object(), 1, user)
    assert rejected.value.status_code == 403
    assert order == ["locked", "fresh"]


@pytest.mark.parametrize("enabled", [False, True])
async def test_pack_obeys_selected_warehouse_mode(api, session, enabled):
    org, _, _, _, _, _ = await prepared(api, session, enabled)
    await session.commit()
    response = await api.post("/wms/pack", json={"organization_id": org,
        "warehouse": "W", "sku_code": "A", "qty": "1", "doc_ref": "TEST-PACK"})
    assert response.status_code == (201 if enabled else 409), response.text
    count = await session.scalar(select(func.count()).select_from(StockMovement).where(StockMovement.reason == "pack"))
    assert count == (2 if enabled else 0)


@pytest.mark.parametrize("endpoint", ["pack", "tasks"])
async def test_execution_requires_explicit_warehouse(api, session, endpoint):
    org, _, _, _, _, _ = await prepared(api, session, True)
    await session.commit()
    response = await api.post(f"/wms/{endpoint}", json={"organization_id": org,
        "sku_code": "A", "qty": "1", "kind": "pick"})
    assert response.status_code == 422, response.text


@pytest.mark.parametrize("reason", ["pick", "putaway", "pack", "production_issue"])
async def test_manual_movement_cannot_bypass_execution_workflow(api, session, reason):
    org, _, _, _, _, _ = await prepared(api, session, False)
    await session.commit()
    response = await api.post("/wms/movements", json={"organization_id": org,
        "warehouse": "W", "sku_code": "A", "qty": "1", "kind": "out", "reason": reason})
    assert response.status_code == 409, response.text
    assert await session.scalar(select(func.count()).select_from(StockMovement).where(StockMovement.kind == "out")) == 0


async def test_unscoped_legacy_operations_reject_writes(api):
    created = await api.post("/wms/ops", json={"title": "Unscoped"})
    updated = await api.patch("/wms/ops/1", json={"stage": "done"})
    assert created.status_code == updated.status_code == 409



async def test_accounting_document_routes_do_not_grant_wms_package(api, session):
    org, facts, _, _, _, command = await prepared(api, session, False)
    await session.commit()
    from core.domain.models import User
    session.add(User(username="allocator", full_name="Synthetic accountant", role="accountant", status="active"))
    await session.commit()
    api.headers["X-User-Roles"] = "accountant"
    prefix = f"/accounting/organizations/{org}/invoices/{facts['document_id']}/document-shipments"
    identity = {"expected_version": facts["version"], "expected_content_sha256": facts["content_sha256"]}
    preview_response = await api.post(prefix + "/preview", json=identity)
    assert preview_response.status_code == 200, preview_response.text
    created = await api.post(prefix, json=command.model_dump(mode="json"))
    assert created.status_code == 201, created.text
    read = await api.get(prefix + f"/by-key/{command.source_key}")
    assert read.status_code == 200, read.text
    history = await api.post(prefix + "/history", json=identity)
    assert history.status_code == 200 and len(history.json()["items"]) == 1, history.text
    denied = await api.get("/wms/ops")
    assert denied.status_code == 403, denied.text


async def test_accounting_source_identity_is_exact_and_crm_remains_closed(api, session):
    org, facts, _, _, _, _ = await prepared(api, session, False)
    from core.domain.models import User
    session.add(User(username="allocator", full_name="Synthetic accountant", role="accountant", status="active"))
    await session.commit()
    api.headers["X-User-Roles"] = "accountant"
    listing = await api.get(f"/accounting/organizations/{org}/stock-issue-invoices")
    assert listing.status_code == 200, listing.text
    assert [row["document_id"] for row in listing.json()["items"]] == [facts["document_id"]]
    path = f"/accounting/organizations/{org}/deals/{facts['deal_id']}/stock-issue-invoices/{facts['document_id']}"
    result = await api.get(path)
    assert result.status_code == 200, result.text
    assert result.json()["content_sha256"] == facts["content_sha256"]
    assert result.json()["document_version"] == facts["version"]
    wrong_deal = await api.get(path.replace(f"/deals/{facts['deal_id']}/", "/deals/9999/"))
    assert wrong_deal.status_code == 404, wrong_deal.text
    wrong_org = await api.get(path.replace(f"/organizations/{org}/", "/organizations/9999/"))
    assert wrong_org.status_code in {403, 404}, wrong_org.text
    crm = await api.get(f"/sales/deals/{facts['deal_id']}")
    assert crm.status_code == 403, crm.text


async def test_mixed_warehouse_reservation_only_creates_wms_tasks(api, session):
    org, facts, allocation, actor = await setup(api, session, create_warehouse=False)
    session.add_all([WarehouseDirectory(organization_id=org,name="W",title="Off",created_by=actor,wms_enabled=False),
        WarehouseDirectory(organization_id=org,name="Z",title="On",created_by=actor,wms_enabled=True),
        StockMovement(organization_id=org,sku_code="A",warehouse="Z",kind="in",qty="10",reason="receipt")])
    allocation.allocations[1].warehouse = "Z"
    await session.flush()
    await reserve(session,org,facts,allocation,actor)
    await apply(session,1,[("A","W",Decimal("2")),("A","Z",Decimal("3"))],organization_id=org,release=False)
    tasks=(await session.scalars(select(Task))).all()
    assert len(tasks)==1 and tasks[0].warehouse=="Z" and tasks[0].qty==3
    facts=await SalesReservationSource().invoice_shipping_source(session,facts["document_id"],organization_id=org,expected_version=facts["version"],expected_content_sha256=facts["content_sha256"])
    basis=await preview(session,org,facts)
    command=ShipmentInput(source_key=uuid4(),expected_version=facts["version"],expected_content_sha256=facts["content_sha256"],
        expected_reservation_digest=basis["reservation_digest"],expected_remaining_digest=basis["remaining_digest"],expected_physical_digest=basis["physical_digest"],
        operation_date=date.today(),evidence="Synthetic mixed warehouses",lines=[{"line_no":1,"warehouse":"W","qty":"1"},{"line_no":2,"warehouse":"Z","qty":"1"}])
    with pytest.raises(HTTPException) as rejected:
        await create(session,org,facts,command,actor,execution_mode="document")
    assert rejected.value.detail=="shipment_batch_mixes_execution_modes"
    assert await session.scalar(select(func.count()).select_from(StockMovement).where(StockMovement.kind=="out"))==0


async def test_event_only_legacy_pick_remains_assignable_but_not_directly_consumable(api, session):
    org, _, _, _ = await setup(api,session)
    await apply(session,1,[("A","W",Decimal("5"))],organization_id=org,release=False)
    task=(await session.scalars(select(Task))).one()
    task_id=task.id
    await session.commit()
    updated=await api.patch(f"/wms/tasks/{task_id}",json={"status":"in_progress","assignee":"Legacy worker"})
    assert updated.status_code==200,updated.text
    denied=await api.patch(f"/wms/tasks/{task_id}",json={"status":"done"})
    assert denied.status_code==409,denied.text
    assert await session.scalar(select(func.count()).select_from(StockMovement).where(StockMovement.kind=="out"))==0


@pytest.mark.parametrize("enabled",[False,True])
async def test_receipt_stock_is_independent_of_optional_putaway(api,session,services,enabled,monkeypatch):
    from modules.wms.models import ReceiptLine
    from modules.wms.primary_receipts import create_from_primary
    from tests import test_wms_primary_receipts as receipt_fixture
    from tests.test_wms_primary_receipts import command
    from tests.test_wms_primary_receipts import setup as receipt_setup
    original_document = receipt_fixture.document
    def selected_warehouse_document():
        data = original_document()
        data.update(warehouse="Main", warehouse_title="Main warehouse")
        return data
    monkeypatch.setattr(receipt_fixture, "document", selected_warehouse_document)
    org,source,core,user,_=await receipt_setup(api,session,services)
    warehouse=await session.scalar(select(WarehouseDirectory).where(WarehouseDirectory.organization_id==org))
    warehouse.wms_enabled=enabled
    binding=await create_from_primary(session,core,user,org,source,command())
    line=await session.get(ReceiptLine,binding.line_bindings[0]["receipt_line_id"])
    line.accepted_qty,line.rejected_qty=Decimal("1.25"),Decimal("0")
    await session.commit()
    path=f"/wms/receipts/{binding.receipt_id}/accept"
    first=await api.post(path)
    assert first.status_code==200,first.text
    assert (await api.post(path)).status_code==200
    movements=(await session.scalars(select(StockMovement))).all()
    assert len(movements)==1 and movements[0].qty==Decimal("1.25")
    assert await session.scalar(select(func.count()).select_from(Task).where(Task.kind=="putaway"))==(1 if enabled else 0)
