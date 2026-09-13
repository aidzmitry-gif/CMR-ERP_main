from sqlalchemy import func, select

from core.services.auth import CurrentUser, get_current_user
from modules.accounting.models import AccessGrant, Entry
from modules.procurement.receipt_documents import (
    ReceiptContent,
    ReceiptDocument,
    ReceiptPosting,
    ReceiptRevision,
)
from modules.procurement.source_gateway import ProcurementSourceService
from tests.accounting.test_procurement_receipt_drafts import document


async def prepare(client, db, book):
    result = await client.post(f"/procurement/organizations/{book[0]}/receipt-documents",
                               json={"key": "reader-source", "document": document()})
    assert result.status_code == 201
    receipt_id = result.json()["id"]
    client.test_app.state.core.services.procurement_source = ProcurementSourceService()
    db.add(AccessGrant(organization_id=book[0], subject="reader", role="reader"))
    await db.commit()
    client.test_app.dependency_overrides[get_current_user] = lambda: CurrentUser("reader", ["finance"])
    return receipt_id, f"/accounting/organizations/{book[0]}/receipts/{receipt_id}/source"


async def test_accounting_reader_reads_source_without_procurement_authority(client, db, book):
    receipt_id, path = await prepare(client, db, book)
    response = await client.get(path)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json()["document"] == ReceiptContent.model_validate(document()).model_dump(mode="json")
    assert response.json()["version"] == 1
    assert response.json()["entry_id"] is None
    assert (await client.get(f"/procurement/organizations/{book[0]}/receipt-documents")).status_code == 403
    assert (await client.get(path.replace(f"/{book[0]}/receipts", "/999/receipts"))).status_code == 403
    assert (await client.get(path.replace(f"/receipts/{receipt_id}/", "/receipts/999/"))).status_code == 404
    assert await db.scalar(select(func.count()).select_from(Entry)) == 0


async def test_posted_source_uses_recorded_revision_not_current_draft(client, db, book):
    receipt_id, path = await prepare(client, db, book)
    row = await db.get(ReceiptDocument, receipt_id)
    row.current_version = 2
    db.add(ReceiptRevision(receipt_id=receipt_id, version=2, actor="later",
                           document={**document(), "invoice_reference": "LATER"}))
    db.add(ReceiptPosting(receipt_id=receipt_id, version=1, entry_id=123,
                          options={}, digest="a" * 64, actor="poster"))
    await db.commit()
    response = await client.get(path)
    assert response.status_code == 200
    assert response.json()["version"] == 1
    assert response.json()["document"]["invoice_reference"] == "INV1"
    assert response.json()["entry_id"] == 123
    assert response.json()["status"] == "posted"


async def test_missing_revision_fails_instead_of_using_different_history(client, db, book):
    receipt_id, path = await prepare(client, db, book)
    row = await db.get(ReceiptDocument, receipt_id)
    row.current_version = 2
    await db.commit()
    assert (await client.get(path)).status_code == 409
    client.test_app.state.core.services.procurement_source = None
    assert (await client.get(path)).status_code == 503
