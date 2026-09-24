# ruff: noqa: F811 -- imported pytest fixtures
import asyncio
from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update

from core.domain.models import Counterparty
from modules.accounting.late_cost_receipts import LateCostCommand
from modules.accounting.models import AccessGrant, Entry, LateCostReceipt, Policy, SourceControl
from modules.procurement.models import Supplier
from modules.wms.models import StockMovement
from tests.accounting.test_postgres import pg_factory  # noqa: F401
from tests.accounting.test_shipment_receipt_postgres import prepare_accounting
from tests.integration.test_invoice_physical_shipments_postgres import physical_pg  # noqa: F401


@pytest.mark.parametrize("same_command", [True, False])
async def test_physical_shipment_consumes_verified_late_cost(physical_pg, same_command):
    api = physical_pg[0]
    factory, org, act, data = await prepare_accounting(physical_pg, full=True, stock_cost=None)
    today = date.today().isoformat()
    async with factory() as session:
        await session.execute(update(AccessGrant).where(AccessGrant.organization_id == org).values(role="accountant"))
        policy = Policy(organization_id=org, effective_from=date.today(), reference="Late cost policy",
            inventory_method="specific", allocation_basis="direct_cost", depreciation_method="straight_line",
            normative_reference="Synthetic", normative_verified=False, approved_by="allocator",
            late_cost_allocation={"basis": "quantity", "rounding": "largest_remainder_cent"})
        session.add(policy)
        await session.flush()
        policy_id = policy.id
        await session.commit()
    receipt_root = f"/procurement/organizations/{org}/receipt-documents"
    async with factory() as session:
        party = Counterparty(name="supplier")
        session.add(party)
        await session.flush()
        supplier = Supplier(name="supplier", unp="", status="active", counterparty_id=party.id)
        session.add(supplier)
        await session.flush()
        supplier_id = supplier.id
        await session.commit()
    source = {"currency": "BYN", "invoice_reference": "receipt-cost", "document_date": today,
        "operation_date": today, "supplier": "supplier", "supplier_id": supplier_id,
        "supplier_unp": "", "contract": "contract", "warehouse": "W",
        "explanation": "Synthetic acquisition", "items": [{"sku": "A", "lot": "L", "quantity": "3",
            "net_amount": "10.00", "vat_rate": "0", "vat_amount": "0.00", "vat_basis": "Synthetic"}]}
    created = await api.post(receipt_root, json={"key": "late-source", "document": source})
    assert created.status_code == 201, created.text
    receipt_id = created.json()["id"]
    options = {"expected_version": 1, "posting_date": today, "policy_id": policy_id,
        "settlement_account": "60", "vat_account": None, "inventory_accounts": ["41.2"]}
    receipt_url = receipt_root + f"/{receipt_id}"
    prepared = await api.post(receipt_url + "/preview", json=options)
    assert prepared.status_code == 200, prepared.text
    posted = await api.post(receipt_url + "/confirm", json={**options, "digest": prepared.json()["digest"]})
    assert posted.status_code == 201, posted.text
    expense = {"invoice_reference": "transport", "document_date": today, "operation_date": today,
        "supplier": "carrier", "contract": "transport", "currency": "BYN", "amount": "2.00",
        "explanation": "Synthetic transport", "receipt_lines": [{"receipt_id": receipt_id, "version": 1, "line_number": 1}]}
    created = await api.post(f"/procurement/organizations/{org}/additional-expenses",
        json={"key": "transport", "document": expense}, headers={"X-Expected-Principal": "allocator"})
    assert created.status_code == 201, created.text
    expense_id = created.json()["id"]
    command = LateCostCommand(allocation={"expected_version": 1, "policy_id": policy_id, "posting_date": today,
        "capitalizable_amount_byn": "2.00", "excluded_amount_byn": "0.00", "classification_evidence": "Synthetic reviewed transport"},
        accounts={"settlement_account": "60"})
    late_url = f"/accounting/organizations/{org}/additional-expenses/{expense_id}"
    prepared = await api.post(late_url + "/posting-preview", json=command.model_dump(mode="json"))
    assert prepared.status_code == 200, prepared.text
    assert prepared.json()["principal"] == "allocator" and not prepared.json()["posted"]
    late_command = {**command.model_dump(mode="json"), "request_key": str(uuid4()),
        "expected_basis_digest": prepared.json()["basis_digest"], "expected_digest": prepared.json()["digest"]}
    revised = await api.put(f"/procurement/organizations/{org}/additional-expenses/{expense_id}",
        json={"expected_version": 1, "document": {**expense, "explanation": "Reviewed transport source revision"}},
        headers={"X-Expected-Principal": "allocator"})
    assert revised.status_code == 200 and revised.json()["version"] == 2, revised.text
    stale_source = await api.post(late_url + "/confirm", json=late_command, headers={"X-Expected-Principal": "allocator"})
    assert stale_source.status_code == 422, stale_source.text
    assert "version changed" in stale_source.json()["detail"]
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(LateCostReceipt)) == 0
        assert await session.scalar(select(SourceControl.entry_id).where(SourceControl.organization_id == org,
            SourceControl.source == f"procurement:additional-expense:{expense_id}")) is None
    command = LateCostCommand.model_validate({**command.model_dump(mode="json"),
        "allocation": {**command.allocation.model_dump(mode="json"), "expected_version": 2}})
    prepared = await api.post(late_url + "/posting-preview", json=command.model_dump(mode="json"))
    assert prepared.status_code == 200, prepared.text
    late_command = {**command.model_dump(mode="json"), "request_key": str(uuid4()),
        "expected_basis_digest": prepared.json()["basis_digest"], "expected_digest": prepared.json()["digest"]}
    assert (await api.post(late_url + "/confirm", json=late_command)).status_code == 422
    assert (await api.post(late_url + "/confirm", json=late_command,
        headers={"X-Expected-Principal": "other"})).status_code == 409
    async with factory() as session:
        await session.execute(update(AccessGrant).where(AccessGrant.organization_id == org).values(role="reader"))
        await session.commit()
    assert (await api.post(late_url + "/posting-preview", json=command.model_dump(mode="json"))).status_code == 403
    assert (await api.post(late_url + "/confirm", json=late_command,
        headers={"X-Expected-Principal": "allocator"})).status_code == 403
    async with factory() as session:
        await session.execute(update(AccessGrant).where(AccessGrant.organization_id == org).values(role="accountant"))
        await session.commit()
    assert (await api.post(f"/accounting/organizations/{org + 999}/additional-expenses/{expense_id}/confirm",
        json=late_command, headers={"X-Expected-Principal": "allocator"})).status_code == 403
    async with factory() as session:
        entries_before = await session.scalar(select(func.count()).select_from(Entry))
    stale = await api.post(late_url + "/confirm", json={**late_command, "expected_basis_digest": "0" * 64},
        headers={"X-Expected-Principal": "allocator"})
    assert stale.status_code == 409, stale.text
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(Entry)) == entries_before
        assert await session.scalar(select(func.count()).select_from(LateCostReceipt)) == 0
    competing = late_command if same_command else {**late_command, "request_key": str(uuid4())}
    results = await asyncio.gather(*[
        api.post(late_url + "/confirm", json=body, headers={"X-Expected-Principal": "allocator"})
        for body in (late_command, competing)])
    assert sorted(response.status_code for response in results) == ([201, 201] if same_command else [201, 409]), [r.text for r in results]
    winner = next(index for index, response in enumerate(results) if response.status_code == 201)
    late_posted = results[winner]
    late_command = (late_command, competing)[winner]
    if same_command:
        assert results[0].json() == results[1].json()
    assert late_posted.status_code == 201, late_posted.text
    assert late_posted.json()["posted"] and late_posted.headers["cache-control"] == "private, no-store"
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(Entry)) == entries_before + 1
        assert await session.scalar(select(func.count()).select_from(LateCostReceipt)) == 1
        assert await session.scalar(select(SourceControl.entry_id).where(SourceControl.organization_id == org,
            SourceControl.source == f"procurement:additional-expense:{expense_id}")) == late_posted.json()["entry_id"]
    late_replay = await api.post(late_url + "/confirm", json=late_command, headers={"X-Expected-Principal": "allocator"})
    assert late_replay.status_code == 201 and late_replay.json() == late_posted.json(), late_replay.text
    status = await api.get(late_url + "/posting")
    assert status.status_code == 200 and status.json()["entry_id"] == late_posted.json()["entry_id"], status.text
    primary = await api.get(f"/procurement/organizations/{org}/additional-expenses/{expense_id}")
    assert primary.status_code == 200 and primary.json()["status"] == "posted" and primary.json()["posted"], primary.text
    assert primary.json()["posting"]["entry_id"] == late_posted.json()["entry_id"]
    second = await api.post(f"/procurement/organizations/{org}/additional-expenses",
        json={"key": "broker", "document": {**expense, "invoice_reference": "broker", "amount": "3.00"}},
        headers={"X-Expected-Principal": "allocator"})
    assert second.status_code == 201, second.text
    second_url = f"/accounting/organizations/{org}/additional-expenses/{second.json()['id']}"
    second_command = {**command.model_dump(mode="json"), "allocation": {
        **command.allocation.model_dump(mode="json"), "expected_version": 1, "capitalizable_amount_byn": "3.00"}}
    second_preview = await api.post(second_url + "/posting-preview", json=second_command)
    assert second_preview.status_code == 200, second_preview.text
    second_posted = await api.post(second_url + "/confirm", json={**second_command, "request_key": str(uuid4()),
        "expected_digest": second_preview.json()["digest"], "expected_basis_digest": second_preview.json()["basis_digest"]},
        headers={"X-Expected-Principal": "allocator"})
    assert second_posted.status_code == 201, second_posted.text
    original_status = await api.get(late_url + "/posting")
    assert original_status.status_code == 200 and original_status.json() == status.json(), original_status.text
    payload = {**data.model_dump(mode="json"), "policy_id": policy_id}
    async with factory() as session:
        warehouse_moves = await session.scalar(select(func.count()).select_from(StockMovement))
    url = f"/accounting/organizations/{org}/shipments/{act['source_key']}"
    prepared = await api.post(url + "/preview", json=payload)
    assert prepared.status_code == 200, prepared.text
    assert prepared.json()["costs"][0]["issue_cost_byn"] == "15.00"
    warehouse_preview = await api.post(
        f"/wms/organizations/{org}/physical-shipments/by-key/{act['source_key']}/accounting-preview", json=payload)
    assert warehouse_preview.status_code == 200, warehouse_preview.text
    assert warehouse_preview.json() == prepared.json()
    body = {**payload, "expected_basis_digest": prepared.json()["basis_digest"]}
    posted = await api.post(url + "/confirm", json=body)
    assert posted.status_code == 201, posted.text
    repeated = await api.post(url + "/confirm", json=body)
    assert repeated.status_code == 201 and repeated.json() == posted.json(), repeated.text
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(StockMovement)) == warehouse_moves
