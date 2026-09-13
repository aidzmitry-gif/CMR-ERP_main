from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select

from core.domain.models import Sku
from core.services.auth import CurrentUser
from modules.wms.models import Receipt, ReceiptLine, StockMovement
from modules.wms.primary_receipts import (
    PrimaryReceiptBinding,
    PrimaryReceiptCommand,
    create_from_primary,
)
from tests.accounting.test_procurement_receipt_drafts import document
from tests.test_wms_organization import book


async def setup(api, session, services):
    org = await book(api)
    data = document()
    data["items"][0].update(quantity="2.00", unit="кг")
    response = await api.post(f"/procurement/organizations/{org}/receipt-documents", json={"key": "physical-source", "document": data})
    assert response.status_code == 201, response.text
    session.add_all([Sku(code="WAREHOUSE-SKU", title="Material", unit="кг"), Sku(code="WRONG-UNIT", title="Box", unit="шт")])
    await session.commit()
    return org, response.json()["id"], SimpleNamespace(services=services), CurrentUser("wms-owner-test", ["director"]), data


def command(quantity="1.25", **changes):
    return PrimaryReceiptCommand.model_validate({"request_key": str(uuid4()), "expected_version": 1,
        "warehouse": "Main", "evidence": "Synthetic explicit SKU and warehouse correspondence",
        "lines": [{"position": 1, "sku_code": "WAREHOUSE-SKU", "quantity": quantity}], **changes})


async def test_partial_primary_receipts_preserve_source_and_replay_without_stock(api, session, services):
    org, source, core, user, _ = await setup(api, session, services)
    first_command = command()
    first = await create_from_primary(session, core, user, org, source, first_command)
    await session.commit()
    again = await create_from_primary(session, core, user, org, source, first_command)
    assert again.receipt_id == first.receipt_id
    assert first.actor == "wms-owner-test"
    assert first.source_snapshot["lines"][0]["unit"] == "кг"
    assert first.line_bindings[0]["source_line"] == f"procurement:receipt:{source}:1:1"
    with pytest.raises(ValueError, match="exceed"):
        await create_from_primary(session, core, user, org, source, command("0.76"))
    second = await create_from_primary(session, core, user, org, source, command("0.75"))
    await session.commit()
    assert second.receipt_id != first.receipt_id
    assert await session.scalar(select(func.count()).select_from(Receipt)) == 2
    assert await session.scalar(select(func.count()).select_from(StockMovement)) == 0
    lines = (await session.scalars(select(ReceiptLine).order_by(ReceiptLine.id))).all()
    assert [line.expected_qty for line in lines] == [Decimal("1.25"), Decimal("0.75")]
    assert all(line.batch_ref == "lot1" and line.accepted_qty is None for line in lines)
    assert (await session.get(Receipt, first.receipt_id)).status == "pending_qc"
    report = await api.get(f"/accounting/organizations/{org}/receipts/{source}/warehouse-reconciliation",
                           headers={"X-User-Roles": "finance"})
    assert report.status_code == 200, report.text
    assert report.headers["cache-control"] == "private, no-store"
    totals = report.json()["rows"][0]
    assert Decimal(totals["prepared"]) == Decimal("2.00")
    assert Decimal(totals["accepted"]) == 0
    assert Decimal(totals["pending_qc"]) == Decimal("2.00")
    assert Decimal(totals["unallocated"]) == 0
    with pytest.raises(ValueError, match="different content"):
        await create_from_primary(session, core, user, org, source, command("0.50", request_key=first_command.request_key))


async def test_primary_change_requires_reconciliation_after_physical_preparation(api, session, services):
    org, source, core, user, data = await setup(api, session, services)
    original = command("1.00")
    created = await create_from_primary(session, core, user, org, source, original)
    await session.commit()
    data["items"][0]["quantity"] = "3.00"
    response = await api.put(f"/procurement/organizations/{org}/receipt-documents/{source}",
                             json={"expected_version": 1, "document": data})
    assert response.status_code == 200, response.text
    with pytest.raises(ValueError, match="reconciliation required"):
        await create_from_primary(session, core, user, org, source, command(expected_version=2))
    assert (await create_from_primary(session, core, user, org, source, original)).receipt_id == created.receipt_id
    assert created.source_snapshot["document"]["items"][0]["quantity"] == "2.00"
    assert await session.scalar(select(func.count()).select_from(PrimaryReceiptBinding)) == 1
    report = await api.get(f"/accounting/organizations/{org}/receipts/{source}/warehouse-reconciliation")
    assert report.status_code == 200, report.text
    assert report.json()["status"] == "version_conflict"
    assert report.json()["rows"] == []
    assert report.json()["source_version"] == 2
    assert report.json()["receipts"][0]["source_version"] == 1


async def test_unit_mismatch_and_invalid_position_do_not_create_receipts(api, session, services):
    org, source, core, user, _ = await setup(api, session, services)
    for position, sku in [(1, "WRONG-UNIT"), (1, "MISSING"), (2, "WAREHOUSE-SKU")]:
        with pytest.raises(ValueError):
            await create_from_primary(session, core, user, org, source, command(lines=[{"position": position, "sku_code": sku, "quantity": "1"}]))
    assert await session.scalar(select(func.count()).select_from(Receipt)) == 0
    assert await session.scalar(select(func.count()).select_from(PrimaryReceiptBinding)) == 0


async def test_primary_receipt_requires_module_and_organization_access(api, session, services):
    org, source, core, _, _ = await setup(api, session, services)
    for user in [CurrentUser("wms-owner-test", ["finance"]), CurrentUser("outsider", ["director"])]:
        with pytest.raises(HTTPException) as error:
            await create_from_primary(session, core, user, org, source, command())
        assert error.value.status_code == 403
    assert await session.scalar(select(func.count()).select_from(Receipt)) == 0


@pytest.mark.parametrize("quantity", [1.25, True, "0.001", "NaN", "0", "-1"])
def test_physical_command_requires_exact_representable_positive_quantity(quantity):
    with pytest.raises(ValidationError):
        command(quantity)


async def test_bound_acceptance_requires_explicit_qc_and_posts_only_accepted(api, session, services):
    org, source, core, user, _ = await setup(api, session, services)
    binding = await create_from_primary(session, core, user, org, source, command())
    await session.commit()
    path = f"/wms/receipts/{binding.receipt_id}/accept"
    response = await api.post(path)
    assert response.status_code == 409 and "explicit QC" in response.text
    assert await session.scalar(select(func.count()).select_from(StockMovement)) == 0
    line = await session.get(ReceiptLine, binding.line_bindings[0]["receipt_line_id"])
    line.accepted_qty, line.rejected_qty = Decimal("1.00"), Decimal("0.25")
    line.reject_reason = "Synthetic QC defect"
    await session.commit()
    response = await api.post(path)
    assert response.status_code == 200, response.text
    assert (await api.post(path)).status_code == 200
    movement = (await session.scalars(select(StockMovement))).one()
    assert movement.qty == Decimal("1.00") and movement.organization_id == org
    assert movement.batch_ref == "lot1" and movement.sku_code == "WAREHOUSE-SKU"
    path = f"/accounting/organizations/{org}/receipts/{source}/warehouse-reconciliation"
    report = await api.get(path, headers={"X-User-Roles": "finance"})
    assert report.status_code == 200, report.text
    totals = report.json()["rows"][0]
    assert Decimal(totals["accepted"]) == Decimal("1.00")
    assert Decimal(totals["rejected"]) == Decimal("0.25")
    assert Decimal(totals["unallocated"]) == Decimal("0.75")
    assert Decimal(totals["pending_qc"]) == 0
    assert report.json()["cost_status"] == "not_assessed"
    assert (await api.get(path, headers={"X-User": "outsider"})).status_code == 403
    assert (await api.get(path.replace(f"/receipts/{source}/", "/receipts/999999/"))).status_code == 404


@pytest.mark.parametrize("change", ["source", "quantity", "lot", "unit"])
async def test_bound_acceptance_rechecks_source_and_physical_mapping(api, session, services, change):
    org, source, core, user, data = await setup(api, session, services)
    binding = await create_from_primary(session, core, user, org, source, command())
    await session.commit()
    line = await session.get(ReceiptLine, binding.line_bindings[0]["receipt_line_id"])
    line.accepted_qty, line.rejected_qty = Decimal("1.25"), Decimal("0.00")
    if change == "quantity":
        line.expected_qty = Decimal("1.50")
    if change == "lot":
        line.batch_ref = "wrong"
    if change == "unit":
        sku = await session.scalar(select(Sku).where(Sku.code == "WAREHOUSE-SKU"))
        sku.unit = "шт"
    await session.commit()
    if change == "source":
        data["invoice_reference"] = "Changed after physical preparation"
        response = await api.put(f"/procurement/organizations/{org}/receipt-documents/{source}",
                                 json={"expected_version": 1, "document": data})
        assert response.status_code == 200, response.text
    response = await api.post(f"/wms/receipts/{binding.receipt_id}/accept")
    assert response.status_code == 409, response.text
    assert await session.scalar(select(func.count()).select_from(StockMovement)) == 0
    assert (await session.get(Receipt, binding.receipt_id)).status == "pending_qc"


@pytest.mark.parametrize("corruption", ["missing", "quantity", "duplicate", "warehouse"])
async def test_reconciliation_refuses_movement_corruption_independently_of_sql_guards(api, session, services, corruption):
    org, source, core, user, _ = await setup(api, session, services)
    binding = await create_from_primary(session, core, user, org, source, command())
    await session.commit()
    line = await session.get(ReceiptLine, binding.line_bindings[0]["receipt_line_id"])
    line.accepted_qty, line.rejected_qty = Decimal("1.25"), Decimal("0")
    await session.commit()
    assert (await api.post(f"/wms/receipts/{binding.receipt_id}/accept")).status_code == 200
    movement = (await session.scalars(select(StockMovement))).one()
    if corruption == "missing":
        await session.delete(movement)
    elif corruption == "quantity":
        movement.qty = Decimal("1.00")
    elif corruption == "warehouse":
        movement.warehouse = "Changed"
    else:
        session.add(StockMovement(organization_id=org, sku_code=movement.sku_code,
                                  warehouse=movement.warehouse, kind="in", qty=movement.qty,
                                  reason="receipt", doc_ref=movement.doc_ref, batch_ref=movement.batch_ref))
    # SQLite fixture deliberately has no PostgreSQL triggers: read validation must stand alone.
    await session.commit()
    report = await api.get(f"/accounting/organizations/{org}/receipts/{source}/warehouse-reconciliation")
    assert report.status_code == 409, report.text
    assert "arrival movements" in report.text


async def test_primary_receipt_api_reads_exact_source_and_replays_preparation(api, session, services):
    org, source, _, _, _ = await setup(api, session, services)
    path = f"/wms/organizations/{org}/primary-receipts/{source}"
    response = await api.get(path + "/source", params={"expected_version": 1})
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json()["lines"][0]["unit"] == "кг"
    assert "document" not in response.json()
    cmd = command().model_dump(mode="json")
    first = await api.post(path, json=cmd)
    assert first.status_code == 201, first.text
    assert (await api.post(path, json=cmd)).json() == first.json()
    assert (await api.post(path, json={**cmd, "warehouse": "Other"})).status_code == 409
    assert (await api.get(path + "/source", params={"expected_version": 2})).status_code == 409
    assert (await api.post(path, json=cmd, headers={"X-User": "outsider"})).status_code == 403
    assert (await api.post(path, json=cmd, headers={"X-User-Roles": "finance"})).status_code == 403
    assert await session.scalar(select(func.count()).select_from(Receipt)) == 1
    assert await session.scalar(select(func.count()).select_from(StockMovement)) == 0


async def test_primary_receipt_api_commit_failure_cannot_return_success(api, session, services, monkeypatch):
    from sqlalchemy.exc import IntegrityError

    org, source, _, _, _ = await setup(api, session, services)

    async def fail():
        raise IntegrityError("Synthetic commit failure", None, Exception("Rollback proof"))

    monkeypatch.setattr(session, "commit", fail)
    response = await api.post(f"/wms/organizations/{org}/primary-receipts/{source}", json=command().model_dump(mode="json"))
    assert response.status_code == 409
    assert await session.scalar(select(func.count()).select_from(Receipt)) == 0
    assert await session.scalar(select(func.count()).select_from(PrimaryReceiptBinding)) == 0
