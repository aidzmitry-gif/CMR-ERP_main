import pytest
from sqlalchemy import func, select

from modules.accounting.models import Entry
from modules.procurement.receipt_documents import ReceiptRevision
from modules.procurement.source_gateway import ProcurementSourceService
from tests.accounting.test_procurement_receipt_drafts import document


async def create(client, org, *, quantity="2.00", unit="шт"):
    data = document()
    data["items"][0].update(quantity=quantity, unit=unit)
    response = await client.post(f"/procurement/organizations/{org}/receipt-documents",
                                json={"key": "warehouse-source", "document": data})
    assert response.status_code == 201, response.text
    return response.json()["id"], data


async def test_warehouse_source_keeps_version_line_identity_and_explicit_units(client, db, book):
    org = book[0]
    receipt, data = await create(client, org)
    gateway = ProcurementSourceService()
    first = await gateway.warehouse_receipt_source(db, org, receipt, 1)
    assert first["lines"] == [{"source_line": f"procurement:receipt:{receipt}:1:1", "position": 1,
                               "sku": "sku1", "lot": "lot1", "quantity": "2.00", "unit": "шт"}]
    assert await gateway.warehouse_receipt_source(db, org, receipt, 1) == first
    data["items"][0]["unit"] = "упак"
    data["items"].append({**data["items"][0]})
    edited = await client.put(f"/procurement/organizations/{org}/receipt-documents/{receipt}",
                              json={"expected_version": 1, "document": data})
    assert edited.status_code == 200, edited.text
    with pytest.raises(ValueError, match="version changed"):
        await gateway.warehouse_receipt_source(db, org, receipt, 1)
    second = await gateway.warehouse_receipt_source(db, org, receipt, 2)
    assert [line["source_line"] for line in second["lines"]] == [
        f"procurement:receipt:{receipt}:2:1", f"procurement:receipt:{receipt}:2:2"]
    old = await db.scalar(select(ReceiptRevision).where(ReceiptRevision.receipt_id == receipt, ReceiptRevision.version == 1))
    assert old.document["items"][0]["unit"] == "шт"
    assert await db.scalar(select(func.count()).select_from(Entry)) == 0
    with pytest.raises(ValueError, match="not found"):
        await gateway.warehouse_receipt_source(db, org + 999, receipt, 2)


@pytest.mark.parametrize("quantity,unit,message", [
    ("2.00", None, "unit of measure"),
    ("2.000001", "шт", "cannot be represented"),
    ("1000000000000", "шт", "cannot be represented"),
])
async def test_warehouse_source_rejects_missing_units_and_incompatible_quantity(client, db, book, quantity, unit, message):
    receipt, _ = await create(client, book[0], quantity=quantity, unit=unit)
    with pytest.raises(ValueError, match=message):
        await ProcurementSourceService().warehouse_receipt_source(db, book[0], receipt, 1)
    assert await db.scalar(select(func.count()).select_from(Entry)) == 0


@pytest.mark.parametrize("unit", ["", "   ", "x" * 33, 123])
async def test_primary_rejects_invalid_unit(client, book, unit):
    data = document()
    data["items"][0]["unit"] = unit
    response = await client.post(f"/procurement/organizations/{book[0]}/receipt-documents",
                                json={"key": "invalid-unit", "document": data})
    assert response.status_code == 422
