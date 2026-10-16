from datetime import datetime

import pytest

from modules.sales.accounting_ownership import DealOwnership
from modules.sales.documents import digest
from modules.sales.models import Deal, DealDocument
from modules.sales.reservation_source import SalesReservationSource


async def source(db, book, *, owned=True, **changes):
    deal = Deal(number="SYN-RESERVE", title="Synthetic", counterparty="Synthetic")
    db.add(deal)
    await db.flush()
    values = dict(deal_id=deal.id, kind="invoice", number="SYN-INVOICE", amount="100.00",
                  status="posted", content_sha256=digest("Synthetic"), original_html="Synthetic",
                  issued_at=datetime(2026, 9, 1), reserve_status="reserved",
                  snapshot_json={"items": [{"sku_code": "TEST", "qty": "1.25"},
                                           {"sku_code": "TEST", "qty": "2.00"}]})
    values.update(changes)
    doc = DealDocument(**values)
    db.add(doc)
    if owned:
        db.add(DealOwnership(deal_id=deal.id, organization_id=book[0], snapshot={}, evidence="Synthetic", actor="tester"))
    await db.commit()
    return doc


async def test_exact_original_owner_and_quantities(db, book):
    doc = await source(db, book)
    facts = await SalesReservationSource().invoice_reservation(db, doc.id)
    assert facts == {"document_id": doc.id, "deal_id": doc.deal_id, "organization_id": book[0],
                     "version": doc.version, "content_sha256": digest("Synthetic"),
                     "lines": [{"line_no": 1, "sku_code": "TEST", "qty": "1.25"},
                               {"line_no": 2, "sku_code": "TEST", "qty": "2.00"}],
                     "reserve_status": "reserved", "quantities": {"TEST": "3.25"}}


async def test_unowned_invoice_is_not_assigned_to_only_book(db, book):
    doc = await source(db, book, owned=False)
    with pytest.raises(ValueError, match="explicitly confirmed"):
        await SalesReservationSource().invoice_reservation(db, doc.id)


@pytest.mark.parametrize("changes", [
    {"kind": "act"}, {"original_html": None}, {"content_sha256": None},
    {"original_html": "Changed original"}, {"content_sha256": "a" * 64},
    {"issued_at": None}, {"status": "draft"}, {"reserve_status": "none"},
    {"snapshot_json": {}}, {"snapshot_json": {"items": [{"sku_code": None, "qty": "1"}]}},
    *[{"snapshot_json": {"items": [{"sku_code": "TEST", "qty": qty}]}}
      for qty in [True, 1.25, "NaN", "Infinity", "0", "-1", "1.001"]],
])
async def test_incomplete_or_inexact_original_rejected(db, book, changes):
    doc = await source(db, book, **changes)
    with pytest.raises(ValueError):
        await SalesReservationSource().invoice_reservation(db, doc.id)


@pytest.mark.parametrize("document_id", [True, "1", 0, -1, 999])
async def test_invalid_or_missing_source_rejected(db, document_id):
    with pytest.raises(ValueError):
        await SalesReservationSource().invoice_reservation(db, document_id)


async def shipping_source(db, doc, source_organization_id, **changes):
    arguments = dict(organization_id=source_organization_id, expected_version=doc.version,
                     expected_content_sha256=doc.content_sha256)
    arguments.update(changes)
    return await SalesReservationSource().invoice_shipping_source(db, doc.id, **arguments)


@pytest.mark.parametrize("status", ["posted", "paid"])
async def test_shipping_exact_live_source(db, book, status):
    doc = await source(db, book, status=status)
    facts = await shipping_source(db, doc, book[0])
    assert facts["document_id"] == doc.id
    assert facts["document_status"] == status
    assert facts["fulfillment_allowed"] is True
    assert facts["lines"][1] == {"line_no": 2, "sku_code": "TEST", "qty": "2.00"}


@pytest.mark.parametrize("changes", [
    {"organization_id": 99999}, {"organization_id": True},
    {"expected_version": 99999}, {"expected_version": True},
    {"expected_content_sha256": "a" * 64}, {"expected_content_sha256": None},
    {"operation": "cancel"}, {"operation": []},
])
async def test_shipping_rejects_mismatched_source(db, book, changes):
    doc = await source(db, book)
    with pytest.raises(ValueError):
        await shipping_source(db, doc, book[0], **changes)


@pytest.mark.parametrize("status,reserve_status", [
    ("cancelled", "released"), ("cancelled", "reserved"), ("posted", "released"),
])
async def test_terminal_shipping_requires_historical_operation(db, book, status, reserve_status):
    doc = await source(db, book, status=status, reserve_status=reserve_status)
    with pytest.raises(ValueError, match="terminal"):
        await shipping_source(db, doc, book[0])
    facts = await shipping_source(db, doc, book[0], operation="historical_claim")
    assert facts["document_status"] == status
    assert facts["fulfillment_allowed"] is False
    # Existing reservation/release replay must still read terminal originals.
    assert (await SalesReservationSource().invoice_reservation(db, doc.id))["document_id"] == doc.id


async def test_historical_claim_never_grants_new_fulfillment(db, book):
    doc = await source(db, book)
    facts = await shipping_source(db, doc, book[0], operation="historical_claim")
    assert facts["fulfillment_allowed"] is False
