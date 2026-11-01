"""Native read proof for the Office picker through existing Accounting scope."""
import hashlib
from datetime import datetime

from sqlalchemy import event

from core.domain.models import Counterparty
from modules.accounting.models import Organization
from modules.sales.accounting_ownership import DealOwnership
from modules.sales.client_document_register import DealClientBinding
from modules.sales.models import Deal, DealDocument


async def test_office_invoice_picker_reads_exact_current_hash_with_book_and_buyer_scope(
    client, db, book,
):
    other_book = Organization(name="Synthetic foreign book ERP394", unp="999999998")
    other_buyer = Counterparty(id=2, name="Synthetic other buyer ERP394", unp="190000002")
    db.add_all([other_book, other_buyer])
    await db.flush()

    async def linked_deal(number, organization_id, buyer_id):
        deal = Deal(number=number, title="Synthetic Office invoice selection",
                    counterparty="Synthetic display only ERP394", counterparty_id=buyer_id)
        db.add(deal)
        await db.flush()
        db.add_all([
            DealOwnership(deal_id=deal.id, organization_id=organization_id,
                          snapshot={"synthetic": True}, evidence="Synthetic book identity", actor="tester"),
            DealClientBinding(deal_id=deal.id, organization_id=organization_id, counterparty_id=buyer_id,
                              snapshot={"client": {"id": buyer_id}}, evidence="Synthetic buyer identity", actor="tester"),
        ])
        await db.flush()
        return deal

    own = await linked_deal("ERP394-OWN", book[0], 1)
    foreign = await linked_deal("ERP394-FOREIGN", other_book.id, 1)
    different_buyer = await linked_deal("ERP394-OTHER-BUYER", book[0], other_buyer.id)

    def invoice(deal, number, **changes):
        html = f"<p>Synthetic original {number}</p>"
        values = dict(deal_id=deal.id, kind="invoice", number=number, status="issued", version=3,
                      issued_at=datetime(2026, 11, 1, 9), original_html=html,
                      content_sha256=hashlib.sha256(html.encode()).hexdigest(),
                      snapshot_json={"organization_id": book[0] if deal != foreign else other_book.id})
        values.update(changes)
        return DealDocument(**values)

    current = invoice(own, "ERP394-CURRENT")
    foreign_invoice = invoice(foreign, "ERP394-FOREIGN-INVOICE")
    other_buyer_invoice = invoice(different_buyer, "ERP394-OTHER-BUYER-INVOICE")
    db.add_all([current, foreign_invoice, other_buyer_invoice])
    await db.flush()
    db.add_all([
        invoice(own, "ERP394-DRAFT", status="draft", issued_at=None),
        invoice(own, "ERP394-NOT-ISSUED", issued_at=None),
        invoice(own, "ERP394-NO-HASH", content_sha256=None),
        invoice(own, "ERP394-SUPERSEDED", superseded_by_id=current.id),
        invoice(own, "ERP394-CONTRACT", kind="contract"),
    ])
    await db.commit()
    own_id, other_id = book[0], other_book.id
    current_id, other_buyer_id = current.id, other_buyer_invoice.id
    current_hash = current.content_sha256
    foreign_hash = foreign_invoice.content_sha256
    original_invoice_number = current.number
    statements = []

    def observe(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "REPLACE")):
            statements.append(statement)

    event.listen(db.bind.sync_engine, "before_cursor_execute", observe)
    try:
        organizations = await client.get("/accounting/organizations")
        assert organizations.status_code == 200, organizations.text
        assert {row["id"] for row in organizations.json()} == {own_id}

        buyer = await client.get(f"/accounting/organizations/{own_id}/sales/buyers?q=190000001")
        assert buyer.status_code == 200, buyer.text
        assert [row["id"] for row in buyer.json()["items"]] == [1]

        selected = await client.get(
            f"/accounting/organizations/{own_id}/settlement-documents?counterparty_id=1&q=ERP394")
        assert selected.status_code == 200, selected.text
        assert selected.headers["cache-control"] == "private, no-store"
        assert selected.json() == {"organization_id": own_id, "counterparty_id": 1, "truncated": False,
                                  "items": [{"source": "sales", "id": current_id, "number": original_invoice_number,
                                             "version": 3, "reference": f"sales:document:{current_id}",
                                             "content_sha256": current_hash}]}

        other = await client.get(
            f"/accounting/organizations/{own_id}/settlement-documents?counterparty_id=2&q=ERP394")
        assert other.status_code == 200, other.text
        assert [row["id"] for row in other.json()["items"]] == [other_buyer_id]
        assert all(row["content_sha256"] != current_hash for row in other.json()["items"])

        denied = await client.get(
            f"/accounting/organizations/{other_id}/settlement-documents?counterparty_id=1&q=ERP394")
        assert denied.status_code == 403, denied.text
        assert current_hash not in denied.text and foreign_hash not in denied.text

        missing = await client.get(
            f"/accounting/organizations/{own_id}/settlement-documents?counterparty_id=999&q=ERP394")
        assert missing.status_code == 409, missing.text
        assert statements == [], "Invoice selection must not write business records"
    finally:
        event.remove(db.bind.sync_engine, "before_cursor_execute", observe)
