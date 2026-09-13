import pytest
from sqlalchemy import func, select

from core.services.auth import CurrentUser, get_current_user
from modules.accounting.models import AccessGrant, Entry
from modules.procurement.receipt_documents import ReceiptRevision


def document():
    return {"currency": "BYN", "invoice_reference": "INV1", "document_date": "2026-09-01",
            "operation_date": "2026-09-02", "supplier": "supplier1", "contract": "contract1",
            "warehouse": "warehouse1", "explanation": "Synthetic primary invoice",
            "items": [{"sku": "sku1", "lot": "lot1", "quantity": "2.000001",
                       "net_amount": "100.01", "vat_rate": "20", "vat_amount": "20.00",
                       "vat_basis": "Synthetic invoice fact"}]}


async def test_order_line_without_order_rejected_and_legacy_payload_unchanged(client, book):
    from modules.procurement.receipt_documents import ReceiptContent
    data = document()
    assert "order_line_id" not in ReceiptContent.model_validate(data).model_dump(mode="json")["items"][0]
    data["items"][0]["order_line_id"] = 1
    response = await client.post(f"/procurement/organizations/{book[0]}/receipt-documents",
                                json={"key": "line-without-order", "document": data})
    assert response.status_code == 422, response.text


async def test_receipt_preserves_exact_order_line_and_rejects_cross_order_or_sku(client, db, book):
    from modules.procurement.models import PurchaseOrder, PurchaseOrderLine
    from modules.procurement.ownership import PurchaseOwnership

    orders = [PurchaseOrder(number=f"line-test-{i}", supplier="supplier1") for i in range(2)]
    db.add_all(orders)
    await db.flush()
    lines = [PurchaseOrderLine(order_id=order.id, sku_code="sku1", qty=10) for order in orders]
    db.add_all(lines)
    for order in orders:
        db.add(PurchaseOwnership(organization_id=book[0], kind="order", source_id=order.id,
                                 snapshot={}, evidence="Synthetic ownership", actor="tester"))
    await db.flush()
    order_ids, line_ids = [row.id for row in orders], [row.id for row in lines]
    await db.commit()
    path = f"/procurement/organizations/{book[0]}/receipt-documents"
    for index, (line_id, sku) in enumerate(((line_ids[1], "sku1"), (line_ids[0], "wrong-sku"), (999999, "sku1"))):
        payload = document()
        payload["items"][0].update(order_id=order_ids[0], order_line_id=line_id, sku=sku)
        response = await client.post(path, json={"key": f"bad-order-line-{index}", "document": payload})
        assert response.status_code == 409, response.text
    payload = document()
    payload["items"][0].update(order_id=order_ids[0], order_line_id=line_ids[0])
    response = await client.post(path, json={"key": "exact-order-line", "document": payload})
    assert response.status_code == 201, response.text
    assert response.json()["revisions"][0]["document"]["items"][0]["order_line_id"] == line_ids[0]
    repeated = await client.post(path, json={"key": "exact-order-line", "document": payload})
    assert repeated.status_code == 201 and repeated.json()["id"] == response.json()["id"]


async def test_primary_draft_preserves_versions_and_never_posts(client, db, book):
    path = f"/procurement/organizations/{book[0]}/receipt-documents"
    data = {"key": "source1", "document": document()}
    first = await client.post(path, json=data)
    repeat = await client.post(path, json=data)
    assert first.status_code == repeat.status_code == 201
    assert first.json()["id"] == repeat.json()["id"]
    assert first.json()["status"] == "draft"
    changed = {**document(), "invoice_reference": "INV1 corrected"}
    second = await client.put(path + f"/{first.json()['id']}", json={"expected_version": 1, "document": changed})
    assert second.status_code == 200
    assert second.json()["version"] == 2
    revisions = second.json()["revisions"]
    assert [r["document"]["invoice_reference"] for r in revisions] == ["INV1", "INV1 corrected"]
    assert revisions[0]["document"]["items"][0]["quantity"] == "2.000001"
    assert all(r["actor"] == "tester" for r in revisions)
    assert (await client.put(path + f"/{first.json()['id']}", json={"expected_version": 1, "document": changed})).status_code == 409
    assert (await client.post(path, json={**data, "document": changed})).status_code == 409
    assert await db.scalar(select(func.count()).select_from(Entry)) == 0
    assert len((await client.get(path)).json()) == 1
    row = await db.scalar(select(ReceiptRevision).where(ReceiptRevision.version == 1))
    row.actor = "tampered"
    with pytest.raises(ValueError, match="immutable"):
        await db.flush()
    await db.rollback()


async def test_source_permission_does_not_grant_ledger_write(client, db, book):
    db.add(AccessGrant(organization_id=book[0], subject="buyer", role="reader"))
    await db.commit()
    # Module authority + book membership permit a procurement draft, not a posting.
    client.test_app.dependency_overrides[get_current_user] = lambda: CurrentUser("buyer", ["procurement"])
    response = await client.post(f"/procurement/organizations/{book[0]}/receipt-documents", json={"key": "buyer1", "document": document()})
    assert response.status_code == 201
    assert (await client.post(f"/accounting/organizations/{book[0]}/entries", json={})).status_code == 403
    listed = await client.get("/procurement/receipt-organizations")
    assert [row["id"] for row in listed.json()] == [book[0]]
    client.test_app.dependency_overrides[get_current_user] = lambda: CurrentUser("buyer", ["warehouse"])
    assert (await client.get(f"/procurement/organizations/{book[0]}/receipt-documents")).status_code == 403
    client.test_app.dependency_overrides[get_current_user] = lambda: CurrentUser("stranger", ["director"])
    assert (await client.get(f"/procurement/organizations/{book[0]}/receipt-documents")).status_code == 403
    assert (await client.get("/procurement/receipt-organizations")).json() == []


@pytest.mark.parametrize("patch", [{"currency": "USD"}, {"currency": None}, {"supplier": ""}])
async def test_draft_does_not_guess_currency_or_supplier(client, book, patch):
    response = await client.post(f"/procurement/organizations/{book[0]}/receipt-documents", json={"key": "bad", "document": {**document(), **patch}})
    assert response.status_code == 422


async def test_primary_draft_commit_failure_is_not_http_success(client, db, book, monkeypatch):
    from sqlalchemy.exc import IntegrityError

    from modules.procurement.receipt_documents import ReceiptDocument

    async def fail():
        raise IntegrityError("synthetic commit failure", None, Exception("rollback test"))

    monkeypatch.setattr(db, "commit", fail)
    response = await client.post(f"/procurement/organizations/{book[0]}/receipt-documents", json={"key": "failed", "document": document()})
    assert response.status_code == 409
    assert await db.scalar(select(func.count()).select_from(ReceiptDocument)) == 0

async def source_options(client, db, book, *, unit=None):
    from datetime import date

    from modules.accounting.models import Account
    db.add(Account(organization_id=book[0], code="41.2", title="Synthetic goods", category="asset", valid_from=date(2026, 1, 1), required_dimensions=[], currency_tracking=False, quantity_tracking=True, cash=False, normative_ref="synthetic"))
    await db.commit()
    data = document()
    data["items"][0].update(vat_rate="0", vat_amount="0.00")
    if unit is not None:
        data["items"][0]["unit"] = unit
    path = f"/procurement/organizations/{book[0]}/receipt-documents"
    created = await client.post(path, json={"key": "post-source", "document": data})
    assert created.status_code == 201
    return path + f"/{created.json()['id']}", {"expected_version": 1, "posting_date": "2026-09-03", "policy_id": book[1], "settlement_account": "60", "vat_account": None, "inventory_accounts": ["41.2"]}


async def test_source_posting_uses_facts_and_freezes_document(client, db, book):
    from modules.procurement.receipt_documents import ReceiptPosting
    path, options = await source_options(client, db, book)
    revised = document()
    revised["invoice_reference"] = "INV1 revised"
    revised["items"][0].update(vat_rate="0", vat_amount="0.00")
    assert (await client.put(path, json={"expected_version": 1, "document": revised})).status_code == 200
    options["expected_version"] = 2
    preview = await client.post(path + "/preview", json=options)
    assert preview.status_code == 200, preview.text
    assert preview.json()["lines"][0]["amount"] == "100.01"
    confirmed = {**options, "digest": preview.json()["digest"]}
    first = await client.post(path + "/confirm", json=confirmed)
    again = await client.post(path + "/confirm", json=confirmed)
    assert first.status_code == again.status_code == 201, first.text
    assert first.json()["entry_id"] == again.json()["entry_id"]
    assert await db.scalar(select(func.count()).select_from(Entry)) == 1
    assert await db.scalar(select(func.count()).select_from(ReceiptPosting)) == 1
    assert (await client.put(path, json={"expected_version": 1, "document": document()})).status_code == 409
    assert (await client.post(path + "/confirm", json={**confirmed, "posting_date": "2026-09-04"})).status_code == 409
    rows = (await client.get(path.rsplit("/", 1)[0])).json()
    assert rows[0]["status"] == "posted"
    assert rows[0]["posting"]["entry_id"] == first.json()["entry_id"]
    source_path = f"/procurement/organizations/{book[0]}/receipt-postings/{first.json()['entry_id']}"
    source = await client.get(source_path)
    assert source.status_code == 200
    assert source.json()["document"] == rows[0]["revisions"][1]["document"]
    assert source.json()["version"] == 2
    assert (await client.get(source_path.rsplit("/", 1)[0] + "/999999")).status_code == 404
    from modules.accounting.models import Organization
    other = Organization(name="Other", unp="999999995")
    db.add(other)
    await db.flush()
    db.add(AccessGrant(organization_id=other.id, subject="tester", role="chief"))
    await db.commit()
    assert (await client.get(f"/procurement/organizations/{other.id}/receipt-postings/{first.json()['entry_id']}")).status_code == 404
    client.test_app.dependency_overrides[get_current_user] = lambda: CurrentUser("stranger", ["director"])
    assert (await client.get(source_path)).status_code == 403


async def test_stale_source_preview_and_reader_cannot_post(client, db, book):
    path, options = await source_options(client, db, book)
    preview = (await client.post(path + "/preview", json=options)).json()
    assert (await client.put(path, json={"expected_version": 1, "document": document()})).status_code == 200
    assert (await client.post(path + "/confirm", json={**options, "digest": preview["digest"]})).status_code == 409
    db.add(AccessGrant(organization_id=book[0], subject="buyer", role="reader"))
    await db.commit()
    client.test_app.dependency_overrides[get_current_user] = lambda: CurrentUser("buyer", ["procurement"])
    assert (await client.post(path + "/preview", json={**options, "expected_version": 2})).status_code == 403
    assert await db.scalar(select(func.count()).select_from(Entry)) == 0


async def test_vat_worksheet_traces_confirmed_primary_revision(client, db, book):
    from datetime import date

    from modules.accounting.models import Account

    path, options = await source_options(client, db, book)
    db.add(Account(organization_id=book[0], code="18", title="Input VAT", category="asset", valid_from=date(2026, 1, 1), required_dimensions=[], currency_tracking=False, quantity_tracking=False, cash=False, normative_ref="synthetic"))
    await db.commit()
    revised = document()
    revised["invoice_reference"] = "INV1 VAT revision"
    assert (await client.put(path, json={"expected_version": 1, "document": revised})).status_code == 200
    options.update(expected_version=2, vat_account="18")
    preview = await client.post(path + "/preview", json=options)
    assert preview.status_code == 200, preview.text
    confirmed = await client.post(path + "/confirm", json={**options, "digest": preview.json()["digest"]})
    assert confirmed.status_code == 201, confirmed.text
    worksheet = await client.get(f"/accounting/organizations/{book[0]}/input-vat-lines", params={"start": "2026-09-01", "end": "2026-09-30"})
    assert worksheet.status_code == 200, worksheet.text
    row, = worksheet.json()["rows"]
    assert row["operation"] == "inventory_purchase"
    assert row["source"] == f"procurement:receipt:{path.rsplit('/', 1)[1]}"
    assert row["source_version"] == 2 and row["amount"] == "20.00"
    assert row["dimensions"]["settlement_document"] == "INV1 VAT revision"
    assert row["dimensions"]["counterparty"] == revised["supplier"]
    assert row["review_issues"] == [] and row["deduction_status"] == "not_assessed"
    primary = await client.get(f"/procurement/organizations/{book[0]}/receipt-postings/{row['entry_id']}")
    assert primary.status_code == 200, primary.text
    assert primary.json()["version"] == 2
    assert primary.json()["document"]["invoice_reference"] == row["dimensions"]["settlement_document"]


async def test_source_link_failure_rolls_back_entry(client, db, book, monkeypatch):
    from sqlalchemy.exc import IntegrityError

    from modules.procurement.receipt_documents import ReceiptPosting
    path, options = await source_options(client, db, book)
    preview = (await client.post(path + "/preview", json=options)).json()
    original = db.flush
    async def failing_flush(*args, **kwargs):
        if any(isinstance(row, ReceiptPosting) for row in db.new):
            raise IntegrityError("synthetic source link failure", {}, Exception())
        return await original(*args, **kwargs)
    monkeypatch.setattr(db, "flush", failing_flush)
    response = await client.post(path + "/confirm", json={**options, "digest": preview["digest"]})
    assert response.status_code == 409
    assert await db.scalar(select(func.count()).select_from(Entry)) == 0
    assert await db.scalar(select(func.count()).select_from(ReceiptPosting)) == 0


async def test_procurement_role_cannot_bypass_accounting_module_access(client, db, book):
    path, options = await source_options(client, db, book)
    preview = (await client.post(path + "/preview", json=options)).json()
    db.add(AccessGrant(organization_id=book[0], subject="buyer", role="accountant"))
    await db.commit()
    client.test_app.dependency_overrides[get_current_user] = lambda: CurrentUser("buyer", ["procurement"])
    assert (await client.post(path + "/preview", json=options)).status_code == 403
    assert (await client.post(path + "/confirm", json={**options, "digest": preview["digest"]})).status_code == 403
    assert await db.scalar(select(func.count()).select_from(Entry)) == 0

async def test_primary_sources_block_closing_and_invalidate_review(client, db, book):
    from datetime import date

    from modules.accounting import reports, service
    from modules.accounting.models import Period
    from modules.accounting.schemas import CloseInput
    path, options = await source_options(client, db, book)
    period = await db.scalar(select(Period).where(Period.organization_id == book[0]))
    first_generation = period.generation
    assert first_generation == 1
    result = await reports.report(db, book[0], date(2026, 9, 1), date(2026, 9, 30))
    assert result["pending_documents"] == 1
    assert result["status"] == "preliminary"
    with pytest.raises(service.AccountingError, match="Unposted primary"):
        await service.close_period(db, book[0], "2026-09", CloseInput(expected_generation=first_generation, evidence={k: "checked" for k in service.CLOSE_STEPS}), "tester")
    preview = (await client.post(path + "/preview", json=options)).json()
    assert (await client.post(path + "/confirm", json={**options, "digest": preview["digest"]})).status_code == 201
    assert (await client.get(f"/accounting/organizations/{book[0]}/source-controls")).json() == []
    with pytest.raises(service.AccountingError, match="Data changed"):
        await service.close_period(db, book[0], "2026-09", CloseInput(expected_generation=first_generation, evidence={k: "checked" for k in service.CLOSE_STEPS}), "tester")
    await service.close_period(db, book[0], "2026-09", CloseInput(expected_generation=period.generation, evidence={k: "checked" for k in service.CLOSE_STEPS}), "tester")
    await db.commit()
    response = await client.post(path.rsplit("/", 1)[0], json={"key": "late-source", "document": document()})
    assert response.status_code == 409
    assert "closed period" in response.text
    assert len((await client.get(path.rsplit("/", 1)[0])).json()) == 1
