"""Existing G12YU source-boundary oracles, reused unchanged on the public port.

Original test source SHA256: 9cbab079e1330706cc36d268366bbd580da82e687f3cd1a4da0532fc687804eb.
Registered-schema admission and migration tests remain separate.
"""
from uuid import uuid4

import pytest


async def _issued_on_order(api, session):
    from modules.sales.models import DealDocument
    from tests.test_invoice_issuance import create, seed

    ids, base = await seed(api, session)
    base["reserve_mode"] = "on_order"
    preview = await api.post(f"/sales/deals/{ids['deal']}/invoice-preview", json=base)
    assert preview.status_code == 200, preview.text
    prepared = preview.json()
    issued = await create(api, ids, {**base, "request_key": "unreserved-cancellation-source",
        "expected_document_version": prepared["document_version"],
        "expected_basis_digest": prepared["basis_digest"], "allocations": [], "unreserved_confirmed": True})
    assert issued.status_code == 201, issued.text
    session.expire_all()
    doc = await session.get(DealDocument, issued.json()["document"]["id"])
    return ids, doc


async def _cancellation_source(session, ids, doc, **changes):
    from modules.sales.reservation_source import SalesReservationSource

    exact = {"organization_id": ids["org"], "expected_version": doc.version,
             "expected_content_sha256": doc.content_sha256, **changes}
    return await SalesReservationSource().invoice_shipping_source(
        session, doc.id, operation="cancellation", **exact,
    )


@pytest.mark.parametrize("case", [
    "genuine_on_order", "foreign_organization", "wrong_version", "wrong_original_hash",
    "legacy_on_order", "marker_without_receipt", "corrupt_original", "corrupt_issuance_receipt",
    "stock_invoice_mislabelled_unreserved",
])
async def test_cancellation_source_exact_initial_on_order(api, session, case):
    from copy import deepcopy

    from sqlalchemy import delete, update

    from modules.sales.invoice_issuance import InvoiceIssuanceReceipt
    from modules.sales.models import DealDocument
    from modules.sales.reservation_source import SalesReservationSource
    from modules.wms.invoice_fulfillment import invoice_fulfillment_snapshot
    from modules.wms.invoice_reservations import _digest
    from tests.test_invoice_issuance import command, create, seed

    if case == "stock_invoice_mislabelled_unreserved":
        ids, base = await seed(api, session)
        body, _ = await command(api, ids, base)
        result = await create(api, ids, body)
        assert result.status_code == 201, result.text
        doc = await session.get(DealDocument, result.json()["document"]["id"])
        await session.execute(update(DealDocument).where(DealDocument.id == doc.id).values(reserve_status="unreserved"))
    else:
        ids, doc = await _issued_on_order(api, session)
    original = (doc.original_html, deepcopy(doc.snapshot_json), doc.content_sha256, doc.status, doc.reserve_status)
    changes = {}
    if case in {"legacy_on_order", "marker_without_receipt"}:
        await session.execute(delete(InvoiceIssuanceReceipt).where(InvoiceIssuanceReceipt.document_id == doc.id))
        if case == "legacy_on_order":
            snapshot = deepcopy(doc.snapshot_json)
            snapshot.pop("issuance_mode")
            await session.execute(update(DealDocument).where(DealDocument.id == doc.id)
                                  .values(status="posted", snapshot_json=snapshot))
    elif case == "corrupt_original":
        await session.execute(update(DealDocument).where(DealDocument.id == doc.id)
                              .values(original_html=doc.original_html + "corrupt"))
    elif case == "corrupt_issuance_receipt":
        receipt = await session.get(InvoiceIssuanceReceipt, doc.id)
        response = deepcopy(receipt.response)
        response["document"]["reserve_status"] = "reserved"
        await session.execute(update(InvoiceIssuanceReceipt).where(InvoiceIssuanceReceipt.document_id == doc.id)
                              .values(response=response))
    elif case == "foreign_organization":
        changes["organization_id"] = ids["org"] + 1
    elif case == "wrong_version":
        changes["expected_version"] = doc.version + 1
    elif case == "wrong_original_hash":
        changes["expected_content_sha256"] = "0" * 64
    await session.commit()
    if case != "genuine_on_order":
        with pytest.raises(ValueError):
            await _cancellation_source(session, ids, doc, **changes)
        return
    source = await _cancellation_source(session, ids, doc)
    assert source["reserve_status"] == "unreserved" and source["reservation_digest"] is None
    assert source["allocations"] == [] and source["fulfillment_allowed"] is False
    observed = await invoice_fulfillment_snapshot(session, ids["org"], source)
    assert observed["observed_state"] == "no_shipment" and observed["coverage_complete"] is False
    assert observed["snapshot"]["reservation"] is None and observed["snapshot"]["physical_basis"] is None
    assert observed["digest"] == _digest({k: v for k, v in observed.items() if k != "digest"})
    for operation in ["fulfill", "historical_claim"]:
        with pytest.raises(ValueError):
            await SalesReservationSource().invoice_shipping_source(session, doc.id, operation=operation,
                organization_id=ids["org"], expected_version=doc.version, expected_content_sha256=doc.content_sha256)
    await session.refresh(doc)
    assert (doc.original_html, doc.snapshot_json, doc.content_sha256, doc.status, doc.reserve_status) == original
    assert not session.new and not session.dirty and not session.deleted


async def test_cancellation_source_refuses_orphan_late_receipt(api, session):
    from modules.sales.invoice_issuance import InvoiceIssuanceReceipt, InvoiceLateReservationReceipt

    ids, doc = await _issued_on_order(api, session)
    initial = await session.get(InvoiceIssuanceReceipt, doc.id)
    session.add(InvoiceLateReservationReceipt(document_id=doc.id, organization_id=ids["org"],
        document_version=doc.version, content_sha256=doc.content_sha256,
        issuance_snapshot_digest=initial.snapshot_digest, request_key="orphan-late", request_hash="a" * 64,
        reservation_digest="", response={}, actor="issuer"))
    await session.commit()
    with pytest.raises(ValueError, match="genuine unreserved"):
        await _cancellation_source(session, ids, doc)


@pytest.mark.parametrize("corruption", ["float_id", "bool_version", "status", "kind"])
async def test_cancellation_source_refuses_initial_response_type_confusion(api, session, corruption):
    from copy import deepcopy

    from sqlalchemy import update

    from modules.sales.invoice_issuance import InvoiceIssuanceReceipt

    ids, doc = await _issued_on_order(api, session)
    receipt = await session.get(InvoiceIssuanceReceipt, doc.id)
    response = deepcopy(receipt.response)
    if corruption == "float_id":
        response["organization_id"] = float(response["organization_id"])
        response["document"]["id"] = float(response["document"]["id"])
    elif corruption == "bool_version":
        assert response["document_version"] == response["document"]["version"] == 1
        response["document_version"] = response["document"]["version"] = True
    elif corruption == "status":
        response["document"]["status"] = "cancelled"
    else:
        response["document"]["kind"] = "contract"
    await session.execute(update(InvoiceIssuanceReceipt).where(InvoiceIssuanceReceipt.document_id == doc.id)
                          .values(response=response))
    await session.commit()
    with pytest.raises(ValueError, match="Initial unreserved issuance response"):
        await _cancellation_source(session, ids, doc)


@pytest.mark.parametrize("kind", ["legacy_stock", "later_reserved_on_order"])
async def test_cancellation_source_preserves_reserved_history(api, session, kind):
    from copy import deepcopy
    from datetime import date, timedelta

    from sqlalchemy import delete, update

    from modules.sales.invoice_issuance import InvoiceIssuanceReceipt
    from modules.sales.models import DealDocument
    from modules.sales.reservation_source import SalesReservationSource
    from tests.test_invoice_issuance import command, create, seed

    if kind == "later_reserved_on_order":
        ids, base = await seed(api, session)
        base.update(reserve_mode="on_order", valid_until=(date.today() + timedelta(days=5)).isoformat())
        preview = await api.post(f"/sales/deals/{ids['deal']}/invoice-preview", json=base)
        assert preview.status_code == 200, preview.text
        facts = preview.json()
        issued = await create(api, ids, {**base, "request_key": "compat-initial-on-order",
            "expected_document_version": facts["document_version"], "expected_basis_digest": facts["basis_digest"],
            "allocations": [], "unreserved_confirmed": True})
        assert issued.status_code == 201, issued.text
        doc = await session.get(DealDocument, issued.json()["document"]["id"])
        original = (doc.original_html, deepcopy(doc.snapshot_json), doc.content_sha256)
        reserved = await api.post(f"/sales/deals/{ids['deal']}/documents/{doc.id}/reservation", json={
            "organization_id": ids["org"], "request_key": "compat-later-reserve", "expected_document_version": doc.version,
            "expected_content_sha256": doc.content_sha256, "allocations": [{"line_no": 1, "warehouse": "W", "qty": "2.00"}],
            "evidence": "Confirmed synthetic stock and complete journal", "journal_complete": True})
        assert reserved.status_code == 201, reserved.text
        await session.refresh(doc)
        assert (doc.original_html, doc.snapshot_json, doc.content_sha256) == original
        assert doc.reserve_mode == "on_order" and doc.reserve_status == "reserved"
    else:
        ids, base = await seed(api, session)
        body, _ = await command(api, ids, base)
        result = await create(api, ids, body)
        assert result.status_code == 201, result.text
        doc = await session.get(DealDocument, result.json()["document"]["id"])
        snapshot = deepcopy(doc.snapshot_json)
        snapshot.pop("issuance_mode")
        await session.execute(delete(InvoiceIssuanceReceipt).where(InvoiceIssuanceReceipt.document_id == doc.id))
        await session.execute(update(DealDocument).where(DealDocument.id == doc.id)
                              .values(status="posted", snapshot_json=snapshot))
        await session.commit()
    expected = await SalesReservationSource().invoice_shipping_source(session, doc.id,
        organization_id=ids["org"], expected_version=doc.version,
        expected_content_sha256=doc.content_sha256, operation="historical_claim")
    assert await _cancellation_source(session, ids, doc) == expected
    assert expected["reserve_status"] == "reserved" and expected["fulfillment_allowed"] is False


@pytest.mark.parametrize("trace", [
    "reservation", "versions", "event_state", "pick_links", "picks", "acts", "releases", "movements",
])
async def test_unreserved_wms_rejects_each_addressed_trace(api, session, trace):
    from datetime import date
    from decimal import Decimal

    from fastapi import HTTPException
    from sqlalchemy import func, select

    from modules.wms.invoice_fulfillment import invoice_fulfillment_snapshot
    from modules.wms.invoice_reservations import InvoiceReservation, InvoiceReservationRelease
    from modules.wms.invoice_shipments import PhysicalShipmentAct
    from modules.wms.models import ReservationVersion, StockMovement, Task
    from modules.wms.reservation_events import ReservationEventState, ReservationPick

    ids, doc = await _issued_on_order(api, session)
    source = await _cancellation_source(session, ids, doc)
    # Deliberately foreign/orphaned synthetic records prove each independent
    # boundary. They are not fabricated evidence for a successful cancellation.
    foreign = ids["org"] + 100
    rows = {
        "reservation": lambda: InvoiceReservation(document_id=doc.id, organization_id=foreign,
            digest="a" * 64, snapshot={}, actor="issuer"),
        "versions": lambda: ReservationVersion(organization_id=foreign, source=f"invoice:{doc.id}:1:orphan",
            version=1, sku_code=ids["code"], warehouse="W", qty=Decimal("0"), evidence="Synthetic orphan", actor="issuer"),
        "event_state": lambda: ReservationEventState(document_id=doc.id, state="released", quantities={}, reserved_items=[]),
        "pick_links": lambda: ReservationPick(document_id=doc.id, task_id=999),
        "picks": lambda: Task(organization_id=foreign, kind="pick", sku_code=ids["code"],
            warehouse="W", qty=Decimal("1"), doc_ref=f"sales:document:{doc.id}", status="canceled"),
        "acts": lambda: PhysicalShipmentAct(organization_id=foreign, document_id=doc.id, document_version=1,
            content_sha256=doc.content_sha256, reservation_digest="a" * 64, source_key=str(uuid4()),
            request_hash="b" * 64, operation_date=date(2026, 9, 1), actor="issuer", snapshot={}, digest="c" * 64),
        "releases": lambda: InvoiceReservationRelease(document_id=doc.id, organization_id=foreign,
            source_key="orphan-release", request_hash="b" * 64, digest="c" * 64, snapshot={}, actor="issuer"),
        "movements": lambda: StockMovement(organization_id=foreign, sku_code=ids["code"], warehouse="W",
            kind="out", qty=Decimal("1"), reason="shipment", doc_ref=f"sales:document:{doc.id}"),
    }
    session.add(rows[trace]())
    await session.commit()
    models = (InvoiceReservation, ReservationVersion, ReservationEventState, ReservationPick,
              Task, PhysicalShipmentAct, InvoiceReservationRelease, StockMovement)
    before = [await session.scalar(select(func.count()).select_from(model)) for model in models]
    with pytest.raises(HTTPException) as refused:
        await invoice_fulfillment_snapshot(session, ids["org"], source)
    assert refused.value.status_code == 409
    assert refused.value.detail == {"code": "unreserved_invoice_has_wms_history", "scope": trace}
    assert before == [await session.scalar(select(func.count()).select_from(model)) for model in models]
    assert not session.new and not session.dirty and not session.deleted
