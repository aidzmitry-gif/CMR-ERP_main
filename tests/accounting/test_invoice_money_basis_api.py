from tests.accounting.test_invoice_settlements import bank, setup


async def test_money_basis_partial_then_full_refund_and_unallocated_receipt(client, db, book):
    doc_id, allocations = await setup(client, db, book)
    url = allocations.removesuffix("settlements") + "money-basis"
    incoming = await bank(client, book, doc_id, "basis-receipt")
    before = (await client.get(url)).json()
    assert before["money_state"] == "history_unknown"
    assert "known_bank_unallocated" in before["blockers"]
    payment = await client.post(allocations, json={"bank_entry_id": incoming, "source_key": "basis-receipt",
        "amount": "100.00", "evidence": "Synthetic"})
    assert payment.status_code == 201, payment.text
    receipt_id = payment.json()["id"]
    for source, value, state, remainder in [("partial", "40.00", "funds_held", "60.00"),
                                           ("rest", "60.00", "fully_refunded", "0.00")]:
        outgoing = await bank(client, book, doc_id, source, value, "payment")
        response = await client.post(allocations, json={"bank_entry_id": outgoing, "source_key": source,
            "amount": value, "refund_of": receipt_id, "evidence": "Synthetic"})
        assert response.status_code == 201, response.text
        result = await client.get(url)
        assert result.status_code == 200, result.text
        basis = result.json()
        assert basis["money_state"] == state
        assert basis["per_receipt_remaining"][0]["remaining"] == remainder
        assert "fulfillment_required" in basis["external_requirements"]
    old_digest = basis["digest"]
    await bank(client, book, doc_id, "unallocated-late", "10.00")
    after = (await client.get(url)).json()
    assert after["digest"] != old_digest and after["money_state"] == "history_unknown"
    assert "known_bank_unallocated" in after["blockers"]


async def test_money_basis_rechecks_scope_and_access(client, db, book):
    from sqlalchemy import select

    from modules.accounting.models import AccessGrant

    doc_id, allocations = await setup(client, db, book)
    url = allocations.removesuffix("settlements") + "money-basis"
    assert (await client.get(f"/sales/organizations/999/invoices/{doc_id}/money-basis")).status_code == 403
    grant = await db.scalar(select(AccessGrant))
    grant.role = "reader"
    await db.commit()
    assert (await client.get(url)).status_code == 403


async def test_money_basis_rejects_incomplete_legacy_original(client, db, book):
    from sqlalchemy import update

    from modules.sales.models import DealDocument

    doc_id, allocations = await setup(client, db, book)
    await db.execute(update(DealDocument).where(DealDocument.id == doc_id)
                     .values(snapshot_json={"currency": "BYN"}).execution_options(synchronize_session=False))
    await db.commit()
    response = await client.get(allocations.removesuffix("settlements") + "money-basis")
    assert response.status_code == 409 and "reconciliation" in response.text


async def test_manual_cash_entry_with_invoice_link_invalidates_money_basis(client, db, book, posting):
    doc_id, allocations = await setup(client, db, book, status="posted")
    url = allocations.removesuffix("settlements") + "money-basis"
    before = (await client.get(url)).json()
    assert before["money_state"] == "no_receipts"
    data = posting("manual-invoice-money", debit="51", credit="62", amount="25.00").model_dump(mode="json")
    data["lines"][0]["dimensions"] = {"bank_statement": "Synthetic manual statement"}
    data["lines"][1]["dimensions"] = {"settlement_document": f"sales:document:{doc_id}"}
    response = await client.post(f"/accounting/organizations/{book[0]}/entries", json=data)
    assert response.status_code == 201, response.text
    after = (await client.get(url)).json()
    assert after["money_state"] == "history_unknown" and after["digest"] != before["digest"]
    assert "bank_evidence_invalid" in after["blockers"]


async def test_bank_allocation_on_another_invoice_cannot_hide_from_basis(client, db, book):
    from modules.sales.invoice_settlements import InvoiceSettlement
    from modules.sales.models import Deal, DealDocument

    doc_id, allocations = await setup(client, db, book)
    url = allocations.removesuffix("settlements") + "money-basis"
    incoming = await bank(client, book, doc_id, "cross-receipt")
    receipt = await client.post(allocations, json={"bank_entry_id": incoming, "source_key": "cross-receipt",
        "amount": "100.00", "evidence": "Synthetic"})
    outgoing = await bank(client, book, doc_id, "cross-refund", "100.00", "payment")
    assert (await client.post(allocations, json={"bank_entry_id": outgoing, "source_key": "cross-refund",
        "amount": "100.00", "refund_of": receipt.json()["id"], "evidence": "Synthetic"})).status_code == 201
    before = (await client.get(url)).json()
    assert before["money_state"] == "fully_refunded"
    # Deliberately inconsistent historical row, not achievable via allocation API.
    deal = Deal(number="PRIVATE-CROSS", title="Private", counterparty="Private")
    db.add(deal)
    await db.flush()
    other = DealDocument(deal_id=deal.id, kind="invoice", number="PRIVATE-INVOICE")
    db.add(other)
    await db.flush()
    db.add(InvoiceSettlement(organization_id=999, document_id=other.id, source_key="PRIVATE-ALLOCATION",
        bank_entry_id=incoming, direction="receipt", amount="20.00", evidence="Private evidence",
        snapshot={}, actor="private"))
    await db.commit()
    response = await client.get(url)
    after = response.json()
    assert after["money_state"] == "history_unknown" and after["digest"] != before["digest"]
    assert {"bank_allocation_scope_mismatch", "bank_overallocated"} <= set(after["blockers"])
    assert "PRIVATE" not in response.text and "private" not in response.text
