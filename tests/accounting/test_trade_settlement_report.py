from datetime import date

from modules.accounting import service
from modules.accounting.models import Account
from modules.accounting.schemas import PostingInput
from modules.sales.models import Deal, DealDocument
from tests.accounting.test_bank_documents import document as bank_document
from tests.accounting.test_invoice_settlements import setup as invoice_setup
from tests.accounting.test_settlement_offsets import offset


def sale(policy_id, document):
    dimensions = {"counterparty": "Buyer at posting", "contract": "Contract-1",
                  "settlement_document": document}
    return PostingInput.model_validate({
        "source": "synthetic-sale-source", "source_version": 1, "operation": "manual",
        "document_date": "2026-09-02", "operation_date": "2026-09-02",
        "posting_date": "2026-09-02", "policy_id": policy_id,
        "rule_version": "test-only", "explanation": "Synthetic posted trade receivable",
        "lines": [
            {"account": "62", "side": "debit", "amount": "120.00", "dimensions": dimensions},
            {"account": "90.1", "side": "credit", "amount": "120.00"},
        ],
    })


async def bank(client, book, document, *, source, day, amount, direction="receipt", account="62",
               dimensions=None):
    result = await client.post(f"/accounting/organizations/{book[0]}/bank/confirm", json=bank_document(
        source=source, statement_reference=source, policy_id=book[1],
        document_date=day, operation_date=day, posting_date=day,
        amount=amount, direction=direction, settlement_account=account,
        settlement_dimensions=dimensions if dimensions is not None else {
            "counterparty": "Buyer at posting", "contract": "Contract-1",
            "settlement_document": document,
        },
    ))
    assert result.status_code == 201, result.text
    return result.json()["id"]


async def get_report(client, org, start="2026-09-01", end="2026-09-30"):
    response = await client.get(f"/accounting/organizations/{org}/reports/trade-settlements",
                                params={"start": start, "end": end})
    assert response.status_code == 200, response.text
    return response.json()


async def test_document_report_uses_posted_partial_payments_not_current_invoice_state(client, db, book):
    document_id, _ = await invoice_setup(client, db, book, status="issued")
    document = f"sales:document:{document_id}"
    sale_entry = await service.post(db, book[0], sale(book[1], document), "tester")
    first_bank = await bank(client, book, document, source="receipt-1", day="2026-09-03", amount="50.00",
                            dimensions={"counterparty": "Buyer at posting", "contract": "Contract-1",
                                        "settlement_document": document, "bank_reference": "statement-extra"})
    early = await get_report(client, book[0], end="2026-09-10")
    row = next(row for row in early["rows"] if row["document"] == document)
    assert row["classification"] == "receivable"
    assert (row["opening_byn"], row["debit_byn"], row["credit_byn"], row["closing_byn"]) == (
        "0.00", "120.00", "50.00", "70.00")
    assert row["bank_receipts_byn"] == "50.00"
    assert early["osv_reconciliation"]["status"] == "matched"
    assert early["osv_reconciliation"]["osv_line_count"] == 2
    assert [movement["entry_id"] for movement in row["movements"]] == [sale_entry.id, first_bank]

    await bank(client, book, document, source="receipt-2", day="2026-09-12", amount="20.00")
    await bank(client, book, document, source="bank-return", day="2026-09-13",
               amount="10.00", direction="payment")
    later = await get_report(client, book[0])
    row = next(row for row in later["rows"] if row["document"] == document)
    assert (row["bank_receipts_byn"], row["bank_payments_byn"], row["closing_byn"]) == (
        "70.00", "10.00", "60.00")
    assert later["totals_byn"]["receivable"] == "60.00"
    assert later["osv_reconciliation"]["status"] == "matched"
    assert [movement["kind"] for movement in row["movements"]] == [
        "posting", "bank_receipt", "bank_receipt", "bank_payment"]
    shifted = await get_report(client, book[0], start="2026-09-10")
    assert shifted["osv_reconciliation"]["status"] == "matched"
    assert shifted["osv_reconciliation"]["accounts"][0]["osv_byn"] == {
        "opening": "70.00", "debit": "10.00", "credit": "20.00", "closing": "60.00"}

    invoice = await db.get(DealDocument, document_id)
    deal = await db.get(Deal, invoice.deal_id)
    invoice.status = "paid"
    deal.counterparty = "Buyer renamed after posting"
    await db.commit()
    assert await get_report(client, book[0]) == later
    assert await get_report(client, book[0], end="2026-09-10") == early


async def test_explicit_advance_and_offset_are_separate_from_document_debt(client, db, book):
    target = "sales:document:customer-42"
    await service.post(db, book[0], sale(book[1], target), "tester")
    advance_dimensions = {"counterparty": "Buyer at posting", "contract": "Contract-1",
                          "settlement_document": "customer-advance:buyer-1"}
    bank_id = await bank(client, book, target, source="advance-1", day="2026-09-03",
                         amount="100.00", account="60", dimensions=advance_dimensions)
    command = offset(bank_id, book[1], target_document=target,
                     target_dimensions={"counterparty": "Buyer at posting", "contract": "Contract-1",
                                        "settlement_document": target})
    preview = await client.post(f"/accounting/organizations/{book[0]}/settlement-offsets/preview", json=command)
    assert preview.status_code == 200, preview.text
    confirmed = await client.post(f"/accounting/organizations/{book[0]}/settlement-offsets/confirm",
                                  json={**command, "basis_digest": preview.json()["basis_digest"],
                                        "digest": preview.json()["digest"]})
    assert confirmed.status_code == 201, confirmed.text
    result = await get_report(client, book[0])
    rows = {row["document"]: row for row in result["rows"]}
    assert rows[target]["closing_byn"] == "60.00"
    assert rows[target]["offset_credit_byn"] == "60.00"
    assert rows["customer-advance:buyer-1"]["closing_byn"] == "-40.00"
    assert rows["customer-advance:buyer-1"]["classification"] == "customer_advance"
    assert result["totals_byn"]["customer_advance"] == "40.00"
    assert result["totals_byn"]["receivable"] == "60.00"


async def test_missing_analytics_stay_unassigned_and_other_books_are_private(client, book):
    await bank(client, book, "unused", source="unknown-party", day="2026-09-05",
               amount="12.00", dimensions={})
    result = await get_report(client, book[0])
    assert result["review_items"][0] == {"code": "incomplete_analytics", "count": 1}
    assert result["rows"][0]["classification"] == "unassigned"
    assert result["totals_byn"]["receivable"] == "0.00"
    assert result["totals_byn"]["unclassified"] == "12.00"
    other = await client.get("/accounting/organizations/999/reports/trade-settlements",
                             params={"start": date(2026, 9, 1).isoformat(), "end": date(2026, 9, 30).isoformat()})
    assert other.status_code == 403


async def test_byn_payment_reduces_the_same_foreign_document_balance(client, db, book):
    document = "sales:document:fx-1"
    dimensions = {"counterparty": "Foreign buyer", "contract": "Contract-FX",
                  "settlement_document": document}
    posting = PostingInput.model_validate({
        "source": "foreign-sale-fx-1", "source_version": 1, "operation": "manual",
        "document_date": "2026-09-02", "operation_date": "2026-09-02",
        "posting_date": "2026-09-02", "policy_id": book[1],
        "rule_version": "test-only", "explanation": "Synthetic foreign invoice",
        "lines": [
            {"account": "62", "side": "debit", "amount": "300.00", "currency": "USD",
             "original_amount": "100.00", "rate": "3.00", "rate_scale": 1,
             "rate_date": "2026-09-02", "rate_source": "Synthetic rate", "dimensions": dimensions},
            {"account": "90.1", "side": "credit", "amount": "300.00"},
        ],
    })
    await service.post(db, book[0], posting, "tester")
    await bank(client, book, document, source="fx-byn-receipt", day="2026-09-03",
               amount="120.00", dimensions=dimensions)
    result = await get_report(client, book[0])
    row = next(row for row in result["rows"] if row["document"] == document)
    assert row["closing_byn"] == "180.00"
    assert row["currencies"] == ["BYN", "USD"]
    assert result["totals_byn"]["receivable"] == "180.00"
    assert result["review_items"][2] == {"code": "mixed_currency_document", "count": 1}
    assert result["osv_reconciliation"]["status"] == "matched"


async def test_report_flags_a_60_62_ledger_line_excluded_from_document_view(client, db, book):
    db.add(Account(organization_id=book[0], code="62.9", title="Misconfigured settlement account",
                   category="asset", valid_from=date(2026, 1, 1), required_dimensions=[],
                   currency_tracking=False, quantity_tracking=False, cash=True,
                   normative_ref="Synthetic misconfiguration"))
    await db.commit()
    entry = await service.post(db, book[0], PostingInput.model_validate({
        "source": "misconfigured-trade", "source_version": 1, "operation": "manual",
        "document_date": "2026-09-05", "operation_date": "2026-09-05",
        "posting_date": "2026-09-05", "policy_id": book[1],
        "rule_version": "test-only", "explanation": "Synthetic chart error",
        "lines": [
            {"account": "62.9", "side": "debit", "amount": "30.00",
             "cash_activity": "operating", "dimensions": {"counterparty": "Buyer",
             "contract": "Contract", "settlement_document": "sales:document:bad"}},
            {"account": "90.1", "side": "credit", "amount": "30.00"},
        ],
    }), "tester")
    result = await get_report(client, book[0])
    check = result["osv_reconciliation"]
    assert check["status"] == "mismatch"
    assert (check["osv_line_count"], check["document_line_count"], check["missing_osv_lines"]) == (1, 0, 1)
    assert check["missing_postings"][0]["entry_id"] == entry.id
    assert check["accounts"][0]["osv_byn"]["closing"] == "30.00"
    assert check["accounts"][0]["documents_byn"]["closing"] == "0.00"
    assert result["review_items"][-1] == {"code": "osv_document_mismatch", "count": 1}
