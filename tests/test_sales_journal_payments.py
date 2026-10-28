"""Synthetic book evidence; journal reads neither post money nor change invoices."""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import delete, select, update

from core.domain.models import User
from core.services.eventbus import EventContext
from modules.accounting.models import AccessGrant, Account, Organization, Policy
from modules.sales.events import on_payment_paid
from modules.sales.invoice_issuance import InvoiceIssuanceReceipt
from modules.sales.journal_payments import (
    JournalPayment,
    aggregate_payments,
    legacy_payment,
    observed_payment,
)
from modules.sales.models import DealDocument
from tests.accounting.test_invoice_settlements import bank
from tests.test_sales_deals_v2 import (
    _deals_v2_parties,  # noqa: F401
    _erp_invoice_command,  # noqa: F401
    _new_deal,
    _seed_sku,
)


@pytest_asyncio.fixture
async def journal_invoice(api, session, _deals_v2_parties, _erp_invoice_command):  # noqa: F811
    deal = await _new_deal(api, "SYN-JOURNAL", amount=120)
    sku = await _seed_sku(session, "SYN-JOURNAL")
    await session.commit()
    line = await api.post(f"/sales/deals/{deal['id']}/items", json={
        "sku_id": sku.id, "qty": 1, "unit_price": "100.00",
    })
    assert line.status_code == 201, line.text
    issued = await api.post(f"/sales/deals/{deal['id']}/documents", json=await _erp_invoice_command(
        deal["id"], reserve_mode="stock",
    ))
    assert issued.status_code == 201, issued.text
    doc, org = issued.json()["document"], issued.json()["organization_id"]
    assert Decimal(str(doc["amount"])) == Decimal("120.00")
    policy = Policy(organization_id=org, effective_from=date(2026, 1, 1), reference="TEST ONLY",
        inventory_method="specific", allocation_basis="direct_cost", depreciation_method="straight_line",
        normative_reference="synthetic", normative_verified=True, approved_by="issuer")
    session.add(policy)
    for code, cash in (("51", True), ("62", False)):
        session.add(Account(organization_id=org, code=code, title="Synthetic", category="asset",
            valid_from=date(2026, 1, 1), required_dimensions=[], currency_tracking=True,
            quantity_tracking=False, cash=cash, normative_ref="synthetic"))
    await session.commit()
    won = await api.post(f"/sales/deals/{deal['id']}/win")
    assert won.status_code == 200, won.text
    return SimpleNamespace(deal=deal["id"], doc=doc, book=(org, policy.id),
        url=f"/sales/organizations/{org}/invoices/{doc['id']}")


async def journal_row(api, invoice):
    response = await api.get("/sales/journal")
    assert response.status_code == 200, response.text
    return next(row for row in response.json() if row["deal_id"] == invoice.deal)


async def allocate(api, invoice, key, amount, refund_of=None):
    entry = await bank(api, invoice.book, invoice.doc["id"], key, amount,
                       "payment" if refund_of else "receipt")
    response = await api.post(invoice.url + "/settlements", json={
        "source_key": key, "bank_entry_id": entry, "amount": amount,
        "refund_of": refund_of, "evidence": "Synthetic actual bank allocation",
    })
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def test_journal_real_bank_partial_paid_refund(api, session, journal_invoice):
    invoice = journal_invoice
    assert (await journal_row(api, invoice))["payment"] == "invoiced"
    receipt = await allocate(api, invoice, "partial", "40.00")
    assert (await journal_row(api, invoice))["payment"] == "partial"
    remaining = await allocate(api, invoice, "balance", "80.00")
    paid = await journal_row(api, invoice)
    assert paid["payment"] == "paid" and paid["payment_source"] == "ledger"
    await allocate(api, invoice, "refund-a", "40.00", receipt)
    assert (await journal_row(api, invoice))["payment"] == "partial"
    await allocate(api, invoice, "refund-b", "80.00", remaining)
    assert (await journal_row(api, invoice))["payment"] == "refunded"
    # Projection and historical ref-only events never mutate the current invoice.
    await on_payment_paid({"ref": invoice.doc["number"]}, EventContext(session, None))
    await session.commit()
    doc = await session.get(DealDocument, invoice.doc["id"])
    assert doc.status == "issued" and doc.reserve_status == "reserved"


@pytest.mark.parametrize("role", ["reader", "accountant", "chief", "revoked", "other_book"])
async def test_journal_exact_book_read_access(api, session, journal_invoice, role):
    invoice = journal_invoice
    await allocate(api, invoice, "paid", "120.00")
    grant = await session.scalar(select(AccessGrant).where(
        AccessGrant.organization_id == invoice.book[0], AccessGrant.subject == "issuer"))
    if role in {"revoked", "other_book"}:
        await session.delete(grant)
        if role == "other_book":
            other = Organization(name="Synthetic foreign book", unp="950000002")
            session.add(other)
            await session.flush()
            session.add(AccessGrant(organization_id=other.id, subject="issuer", role="chief"))
    else:
        grant.role = role
    await session.commit()
    row = await journal_row(api, invoice)
    assert row["payment"] == ("unknown" if role in {"revoked", "other_book"} else "paid")
    if role in {"revoked", "other_book"}:
        assert row["payment_reason"] == "organization_access_unavailable"
        assert row["payment_source"] == "unknown"
    # A journal reader gains no allocation authority.
    if role in {"reader", "accountant"}:
        assert (await api.get(invoice.url + "/settlements")).status_code == 403


@pytest.mark.parametrize("visibility", ["all", "own"])
async def test_journal_persisted_sales_scope_does_not_expand_access(api, session, journal_invoice, visibility):
    invoice = journal_invoice
    await allocate(api, invoice, "paid", "120.00")
    session.add(User(username="synthetic-journal-reader", full_name="Synthetic Sales reader",
        employee_id=873, role="sales", status="active", deal_visibility=visibility))
    session.add(AccessGrant(organization_id=invoice.book[0], subject="synthetic-journal-reader", role="reader"))
    await session.commit()
    api.headers.update({"X-User": "synthetic-journal-reader", "X-User-Roles": "sales"})
    response = await api.get("/sales/journal")
    if visibility == "own":
        # This aggregate route remains outside the existing Own-route allowlist.
        assert response.status_code == 403
    else:
        assert response.status_code == 200, response.text
        row = next(row for row in response.json() if row["deal_id"] == invoice.deal)
        assert row["payment"] == "paid" and row["payment_source"] == "ledger"
        assert (await api.get(invoice.url + "/settlements")).status_code == 403


@pytest.mark.parametrize("failure", ["disabled", "unavailable", "unauthorized", "invalid_bank", "unallocated"])
async def test_journal_unverified_is_unknown(api, journal_invoice, monkeypatch, failure):
    invoice = journal_invoice
    services = api._transport.app.state.core.services
    if failure == "unallocated":
        await bank(api, invoice.book, invoice.doc["id"], "not-allocated", "120.00")
    elif failure == "disabled":
        monkeypatch.setattr(services, "accounting", None)
    elif failure == "invalid_bank":
        monkeypatch.setattr(services.accounting, "invoice_bank_basis", AsyncMock(return_value=[{"invalid": True}]))
    else:
        monkeypatch.setattr(services.accounting, "invoice_bank_basis", AsyncMock(
            side_effect=HTTPException(403 if failure == "unauthorized" else 503, "PRIVATE SYNTHETIC DETAIL")))
    row = await journal_row(api, invoice)
    assert row["payment"] == "unknown" and row["payment_source"] == "unknown"
    assert "PRIVATE SYNTHETIC DETAIL" not in str(row)


@pytest.mark.parametrize("corruption", ["missing_receipt", "receipt_digest", "original"])
async def test_journal_corrupted_current_evidence_has_no_legacy_fallback(api, session, journal_invoice, corruption):
    invoice = journal_invoice
    # Deliberate SQLite corruption exercises fail-closed reads; PG forbids these writes.
    if corruption == "missing_receipt":
        await session.execute(delete(InvoiceIssuanceReceipt).where(InvoiceIssuanceReceipt.document_id == invoice.doc["id"]))
    elif corruption == "receipt_digest":
        await session.execute(update(InvoiceIssuanceReceipt).where(InvoiceIssuanceReceipt.document_id == invoice.doc["id"])
                              .values(snapshot_digest="f" * 64))
    else:
        await session.execute(update(DealDocument).where(DealDocument.id == invoice.doc["id"]).values(original_html="corrupt"))
    await session.commit()
    row = await journal_row(api, invoice)
    assert row["payment"] == "unknown" and row["payment_source"] == "unknown"


@pytest.mark.parametrize("state,received,refunded,blockers,expected", [
    ("no_receipts", "0", "0", (), "invoiced"),
    ("funds_held", "99.99", "0", ("funds_not_fully_refunded",), "partial"),
    ("funds_held", "100", "0", ("funds_not_fully_refunded",), "paid"),
    ("funds_held", "200", "0", (), "paid"),
    ("funds_held", "100", "0.01", (), "partial"),
    ("fully_refunded", "100", "100", (), "refunded"),
    ("history_unknown", "100", "0", (), "unknown"),
    ("funds_held", "100", "0", ("known_bank_unallocated",), "unknown"),
    ("funds_held", "100", "101", (), "unknown"),
    ("funds_held", "NaN", "0", (), "unknown"),
])
def test_exact_invoice_projection(state, received, refunded, blockers, expected):
    doc = SimpleNamespace(number="SYN-INV", amount=Decimal("100"), status="issued")
    basis = SimpleNamespace(money_state=state, received=received, refunded=refunded, blockers=blockers)
    assert observed_payment(doc, basis).payment == expected


def test_multiple_invoices_cannot_share_overpayment_and_unknown_dominates():
    first = observed_payment(SimpleNamespace(number="A", amount=Decimal("100"), status="issued"),
        SimpleNamespace(money_state="funds_held", received="200", refunded="0", blockers=()))
    unpaid = JournalPayment("invoiced", "B")
    assert aggregate_payments([first, unpaid]).payment == "partial"
    assert aggregate_payments([first, JournalPayment("unknown", "B")]).payment == "unknown"
    assert aggregate_payments([first, JournalPayment("paid", "B")]).payment == "paid"
    assert aggregate_payments([first, JournalPayment("cancelled", "B")]).payment == "paid"


def test_cancelled_requires_verified_receipt_and_no_money_review():
    doc = SimpleNamespace(number="A", amount=Decimal("100"), status="cancelled")
    empty = SimpleNamespace(money_state="no_receipts", received="0", refunded="0", blockers=())
    assert observed_payment(doc, empty).payment == "unknown"
    assert observed_payment(doc, empty, cancellation_verified=True).payment == "cancelled"
    empty.blockers = ("cancelled_invoice_money_review_required",)
    assert observed_payment(doc, empty, cancellation_verified=True).payment == "unknown"


def test_legacy_source_is_explicit_and_not_current_issued():
    legacy = legacy_payment([SimpleNamespace(status="paid", number="OLD")])
    assert legacy == JournalPayment("paid", "OLD", "legacy", "legacy_document_status")
    assert legacy_payment([]) == JournalPayment("none", source="none")
    assert legacy_payment([SimpleNamespace(status="issued", number="CURRENT")]).payment == "unknown"
