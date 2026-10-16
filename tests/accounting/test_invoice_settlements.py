from datetime import date, datetime

import pytest
from sqlalchemy import select

from modules.sales import invoice_settlements as settlements
from modules.sales.accounting_ownership import DealOwnership
from modules.sales.documents import digest
from modules.sales.models import Deal, DealDocument
from tests.accounting.test_bank_documents import document


async def setup(client, db, book, status="paid"):
    client.test_app.include_router(settlements.router, prefix="/sales")
    deal = Deal(number="SYN-MONEY", title="Synthetic", counterparty="Synthetic")
    db.add(deal)
    await db.flush()
    doc = DealDocument(deal_id=deal.id, kind="invoice", number="SYN-INVOICE", amount="100.00",
                       status=status, content_sha256=digest("Synthetic"), original_html="Synthetic", reserve_status="reserved",
                       issued_at=datetime(2026, 9, 1), valid_until=date(2026, 1, 1),
                       snapshot_json={"currency": "BYN", "amount": "100.00", "deal": {"counterparty": "Buyer at issue"},
                                      "items": [{"sku_code": "TEST", "qty": "1"}]})
    db.add_all([doc, DealOwnership(deal_id=deal.id, organization_id=book[0], snapshot={}, evidence="Synthetic", actor="tester")])
    await db.commit()
    return doc.id, f"/sales/organizations/{book[0]}/invoices/{doc.id}/settlements"


async def bank(client, book, doc_id, source, amount="100.00", direction="receipt", **changes):
    response = await client.post(f"/accounting/organizations/{book[0]}/bank/confirm", json=document(
        policy_id=book[1], source=source, statement_reference=source, amount=amount,
        direction=direction, settlement_dimensions={"settlement_document": f"sales:document:{doc_id}"}, **changes))
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def test_receipt_partial_full_refund_and_replay(client, db, book):
    doc_id, url = await setup(client, db, book)
    incoming = await bank(client, book, doc_id, "in")
    data = {"bank_entry_id": incoming, "source_key": "in", "amount": "100.00", "evidence": "Synthetic bank review"}
    receipt = await client.post(url, json=data)
    assert receipt.status_code == 201, receipt.text
    assert (await client.post(url, json=data)).json() == receipt.json()
    assert (await client.post(url, json={**data, "source_key": "duplicate"})).status_code == 409
    for key, amount in (("partial", "40.00"), ("remaining", "60.00")):
        outgoing = await bank(client, book, doc_id, key, amount, "payment")
        result = await client.post(url, json={"bank_entry_id": outgoing, "source_key": key,
            "amount": amount, "refund_of": receipt.json()["id"], "evidence": "Synthetic refund review"})
        assert result.status_code == 201, result.text
        view = (await client.get(url)).json()
        assert view["net_received"] == ("60.00" if key == "partial" else "0.00")
        assert view["cancellation_authorized"] is False
    doc = await db.get(DealDocument, doc_id)
    assert doc.status == "paid" and doc.reserve_status == "reserved"
    row = await db.scalar(select(settlements.InvoiceSettlement))
    row.amount = 1
    with pytest.raises(ValueError, match="cannot be changed"):
        await db.flush()
    await db.rollback()


async def test_money_rejects_wrong_invoice_missing_receipt_and_overrefund(client, db, book):
    doc_id, url = await setup(client, db, book)
    wrong = await bank(client, book, doc_id + 1, "wrong")
    data = {"bank_entry_id": wrong, "source_key": "test", "amount": "100.00", "evidence": "Synthetic"}
    assert (await client.post(url, json=data)).status_code == 409
    outgoing = await bank(client, book, doc_id, "refund", "101.00", "payment")
    assert (await client.post(url, json={**data, "bank_entry_id": outgoing})).status_code == 409
    incoming = await bank(client, book, doc_id, "receipt")
    receipt = await client.post(url, json={**data, "bank_entry_id": incoming})
    assert receipt.status_code == 201, receipt.text
    assert (await client.post(url, json={**data, "bank_entry_id": outgoing, "source_key": "over",
        "amount": "101.00", "refund_of": receipt.json()["id"]})).status_code == 409


async def test_money_access(client, db, book):
    from modules.accounting.models import AccessGrant
    doc_id, url = await setup(client, db, book)
    assert (await client.get(url.replace(f"organizations/{book[0]}", "organizations/999"))).status_code == 403
    grant = await db.scalar(select(AccessGrant))
    grant.role = "reader"
    await db.commit()
    assert (await client.get(url)).status_code == 403


async def test_corrected_bank_requires_reconciliation(client, db, book, posting):
    from modules.accounting import service

    doc_id, url = await setup(client, db, book)
    entry_id = await bank(client, book, doc_id, "receipt")
    data = {"bank_entry_id": entry_id, "source_key": "receipt", "amount": "100.00", "evidence": "Synthetic"}
    assert (await client.post(url, json=data)).status_code == 201
    await service.post(db, book[0], posting("correction", debit="62", credit="51", correction_of=entry_id), "tester")
    await db.commit()
    assert (await client.get(url)).status_code == 409
    assert (await client.post(url, json={**data, "source_key": "new", "amount": "1"})).status_code == 409


async def test_partial_receipt_blocks_expiry_and_status_cancellation(client, db, book):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock

    from modules.accounting.gateway import AccountingService
    from modules.sales.reserve import tick_invoice_reserve

    doc_id, url = await setup(client, db, book, status="posted")
    entry_id = await bank(client, book, doc_id, "partial", "10.00")
    response = await client.post(url, json={"bank_entry_id": entry_id, "source_key": "partial", "amount": "10.00", "evidence": "Synthetic"})
    assert response.status_code == 201, response.text
    stock, bus = SimpleNamespace(release=AsyncMock()), SimpleNamespace(emit=Mock())
    # Make the already-expired date part of the immutable original at creation.
    await tick_invoice_reserve(db, SimpleNamespace(stock=stock, event_bus=bus, accounting=AccountingService()))
    stock.release.assert_not_awaited()
    doc = await db.get(DealDocument, doc_id)
    assert doc.status == "posted" and doc.reserve_status == "reserved"
    doc.status = "cancelled"
    with pytest.raises(ValueError, match="подтверждённым поступлением"):
        await db.flush()
    await db.rollback()


async def test_invoice_picker_scopes_history_pagination_and_literal_search(client, db, book):
    from modules.sales.access import DealAccess, get_deal_access

    doc_id, _ = await setup(client, db, book)
    deal = await db.scalar(select(Deal))
    deal.counterparty = "Renamed today"
    foreign = Deal(number="OTHER", title="Other", counterparty="Other")
    db.add(foreign)
    await db.flush()
    db.add_all([
        DealOwnership(deal_id=foreign.id, organization_id=999, snapshot={}, evidence="Other", actor="other"),
        DealDocument(deal_id=foreign.id, kind="invoice", number="FOREIGN", amount=1),
        DealDocument(deal_id=deal.id, kind="invoice", number="INV%literal", amount=5),
        DealDocument(deal_id=deal.id, kind="contract", number="CONTRACT", amount=1),
    ])
    await db.commit()
    url = f"/sales/organizations/{book[0]}/invoices"
    first = await client.get(url, params={"limit": 1})
    assert first.status_code == 200, first.text
    assert first.json()["next_after_id"] == doc_id
    item = first.json()["items"][0]
    assert item["id"] == doc_id and item["counterparty"] == "Buyer at issue"
    assert item["available_for_settlement"] is True
    second = (await client.get(url, params={"after_id": doc_id})).json()
    assert [row["number"] for row in second["items"]] == ["INV%literal"]
    assert second["items"][0]["available_for_settlement"] is False
    assert second["next_after_id"] is None
    literal = (await client.get(url, params={"q": "%"})).json()
    assert [row["number"] for row in literal["items"]] == ["INV%literal"]
    assert (await client.get(url, params={"limit": 101})).status_code == 422
    client.test_app.dependency_overrides[get_deal_access] = lambda: DealAccess("own", 77)
    assert (await client.get(url)).json()["items"] == []


@pytest.mark.parametrize("amount", [0, "-1", "NaN", "Infinity", 1.25, True, "0.001"])
def test_invalid_money_rejected(amount):
    with pytest.raises(ValueError):
        settlements.AllocationInput(source_key="test", bank_entry_id=1, amount=amount, evidence="test")
