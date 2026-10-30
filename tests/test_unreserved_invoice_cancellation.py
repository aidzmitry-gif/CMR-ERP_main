"""Regression specification for an issued invoice with no reservation."""
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from modules.office import shipping_associations as office_shipping  # noqa: F401
from modules.sales import shipping_associations as sales_shipping  # noqa: F401
from modules.sales.models import DealDocument
from modules.sales.reservation_source import SalesReservationSource
from modules.wms.invoice_reservations import InvoiceReservation, InvoiceReservationRelease
from modules.wms.models import StockMovement
from modules.wms.reservation_events import ReservationEventState
from tests.test_invoice_cancellation import cancel_request
from tests.test_invoice_issuance import create, erp_money_flow, seed


async def issue_unreserved(api, session):
    ids, base = await seed(api, session)
    base["reserve_mode"] = "on_order"
    invoice_preview = await api.post(f"/sales/deals/{ids['deal']}/invoice-preview", json=base)
    assert invoice_preview.status_code == 200, invoice_preview.text
    preview = invoice_preview.json()
    command = {**base, "request_key": "synthetic-on-order-regression", "allocations": [],
               "unreserved_confirmed": True, "expected_document_version": preview["document_version"],
               "expected_basis_digest": preview["basis_digest"]}
    issued = await create(api, ids, command)
    assert issued.status_code == 201, issued.text
    invoice = issued.json()["document"]
    assert invoice["reserve_status"] == "unreserved"
    assert await session.scalar(select(func.count()).select_from(InvoiceReservation)) == 0
    return ids, invoice


async def test_unreserved_source_is_observable_only_for_cancellation(api, session):
    ids, invoice = await issue_unreserved(api, session)
    source = SalesReservationSource()
    exact = {"organization_id": ids["org"], "expected_version": invoice["version"],
             "expected_content_sha256": invoice["content_sha256"]}
    for operation in ("fulfill", "historical_claim"):
        with pytest.raises(ValueError, match="known reservation state"):
            await source.invoice_shipping_source(session, invoice["id"], **exact, operation=operation)
    observed = await source.invoice_shipping_source(session, invoice["id"], **exact, operation="cancellation")
    assert observed["reserve_status"] == "unreserved"
    assert observed["issuance_receipt"]["document_id"] == invoice["id"]
    assert observed["reservation_digest"] is None
    assert observed["fulfillment_allowed"] is False
    assert await session.scalar(select(func.count()).select_from(InvoiceReservationRelease)) == 0


async def test_on_order_invoice_cancellation_preview_accepts_verified_no_reserve(api, session):
    ids, invoice = await issue_unreserved(api, session)
    prefix = f"/sales/organizations/{ids['org']}/invoices/{invoice['id']}"
    money = await api.get(prefix + "/money-reconciliation")
    assert money.status_code == 200, money.text
    facts = money.json()
    reconciliation = await api.post(prefix + "/money-reconciliation", json={
        "source_key": str(uuid4()), "expected_basis_digest": facts["basis_digest"],
        "history_from": facts["required_history_from"], "history_through": facts["required_history_through"],
        "evidence": "Synthetic complete bank and cash reconciliation",
        "source_references": ["Synthetic bank archive", "Synthetic cash archive"],
        "all_money_sources_checked": True,
    })
    assert reconciliation.status_code == 201, reconciliation.text
    original = await session.get(DealDocument, invoice["id"])
    original_fields = (original.original_html, original.content_sha256, original.version)
    cancellation_preview = await api.post(prefix + "/cancellation/preview", json={
        "expected_version": invoice["version"], "expected_content_sha256": invoice["content_sha256"],
    })
    await session.refresh(original)
    assert (original.original_html, original.content_sha256, original.version) == original_fields
    assert (original.status, original.reserve_status) == ("issued", "unreserved")
    assert await session.scalar(select(func.count()).select_from(InvoiceReservation)) == 0
    assert await session.scalar(select(func.count()).select_from(InvoiceReservationRelease)) == 0
    assert cancellation_preview.status_code == 200, cancellation_preview.text
    basis = cancellation_preview.json()
    assert basis["cancellation_authorized"] is False
    assert basis["reservation_digest"] is None
    observed = basis["sections"]["wms_pick"]["facts"]
    assert observed["reservation"] is None
    assert observed["remaining"]["reservation_absent"] is True
    assert {"reservation", "versions", "event_state", "pick_links", "picks", "acts", "releases", "movements"} == set(observed["remaining"]["checked_scopes"])


@pytest.mark.parametrize("conflict", ["reservation", "event", "movement"])
async def test_unreserved_preview_rejects_contradictory_warehouse_records(api, session, conflict):
    ids, invoice = await issue_unreserved(api, session)
    if conflict == "reservation":
        session.add(InvoiceReservation(document_id=invoice["id"], organization_id=ids["org"],
            digest="a" * 64, snapshot={}, actor="synthetic"))
    elif conflict == "event":
        session.add(ReservationEventState(document_id=invoice["id"], state="reserved",
            quantities={}, reserved_items=[]))
    else:
        session.add(StockMovement(organization_id=ids["org"], sku_code="SYNTHETIC", warehouse="W",
            kind="out", qty=1, reason="shipment", doc_ref=f"sales:document:{invoice['id']}"))
    await session.flush()
    # Identity middleware opens its own session. Persist this synthetic history
    # before the HTTP boundary, as a real prior warehouse operation would be.
    await session.commit()
    response = await api.post(f"/sales/organizations/{ids['org']}/invoices/{invoice['id']}/cancellation/preview",
        json={"expected_version": invoice["version"], "expected_content_sha256": invoice["content_sha256"]})
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "unreserved_invoice_has_wms_history"
    assert await session.scalar(select(func.count()).select_from(InvoiceReservationRelease)) == 0


@pytest.mark.parametrize("paid_refunded", [False, True])
async def test_unreserved_cancellation_preserves_original_without_fake_release(api, session, paid_refunded):
    from core.domain.models import OutboxEvent
    from modules.sales.invoice_cancellation import InvoiceCancellationReceipt
    from modules.wms.invoice_shipments import PhysicalShipmentAct

    if paid_refunded:
        from modules.accounting.models import Policy
        await erp_money_flow(api, session, reserve_mode="on_order")
        doc = await session.get(DealDocument, 1)
        doc.status = "paid"
        ids = {"org": await session.scalar(select(Policy.organization_id))}
        invoice = {"id": doc.id, "version": doc.version, "content_sha256": doc.content_sha256}
    else:
        ids, invoice = await issue_unreserved(api, session)
    doc = await session.get(DealDocument, invoice["id"])
    original = (doc.original_html, doc.content_sha256, doc.version, doc.amount)
    physical_before = [await session.scalar(select(func.count()).select_from(model))
                       for model in (StockMovement, PhysicalShipmentAct)]
    await session.commit()
    path, data = await cancel_request(api, ids["org"], {
        "version": invoice["version"], "content_sha256": invoice["content_sha256"]})
    response = await api.post(path, json=data)
    assert response.status_code == 201, response.text
    assert response.json()["stock_outcome"] == "no_stock_release"
    assert response.json()["reserve_status"] == "unreserved"
    assert response.json()["release_id"] is None
    assert response.json()["customer_notification"] == "not_sent"
    assert (await api.post(path, json=data)).json() == response.json()
    assert (await api.post(path, json={**data, "request_key": str(uuid4())})).status_code == 409
    await session.refresh(doc)
    assert (doc.status, doc.reserve_status) == ("cancelled", "unreserved")
    assert (doc.original_html, doc.content_sha256, doc.version, doc.amount) == original
    assert physical_before == [await session.scalar(select(func.count()).select_from(model))
                              for model in (StockMovement, PhysicalShipmentAct)]
    assert await session.scalar(select(func.count()).select_from(InvoiceReservation)) == 0
    assert await session.scalar(select(func.count()).select_from(InvoiceReservationRelease)) == 0
    assert await session.scalar(select(func.count()).select_from(InvoiceCancellationReceipt)) == 1
    assert await session.scalar(select(func.count()).select_from(OutboxEvent).where(
        OutboxEvent.event_type == "sales.invoice.cancelled")) == 1
    from types import SimpleNamespace

    from fastapi import HTTPException

    from modules.sales.invoice_cancellation import cancellation_digest, cancellation_output

    saved = await session.scalar(select(InvoiceCancellationReceipt))
    values = {column.name: getattr(saved, column.name) for column in InvoiceCancellationReceipt.__table__.columns}
    for changes in ({"release_id": 1}, {"snapshot": {**saved.snapshot, "stock_outcome": "unknown"}},
                    {"snapshot": {k: v for k, v in saved.snapshot.items() if k != "no_stock_release"}}):
        corrupt = SimpleNamespace(**{**values, **changes})
        corrupt.digest = cancellation_digest(corrupt)
        with pytest.raises(HTTPException, match="stock outcome requires reconciliation"):
            cancellation_output(corrupt)


async def test_unreserved_cancellation_rejects_missing_or_mismatched_review(api, session):
    from modules.sales.invoice_cancellation import InvoiceCancellationReceipt

    ids, invoice = await issue_unreserved(api, session)
    endpoint = f"/sales/organizations/{ids['org']}/invoices/{invoice['id']}/cancel"
    data = {"expected_version": invoice["version"], "expected_content_sha256": invoice["content_sha256"],
        "request_key": str(uuid4()), "fulfillment_review_id": str(uuid4()),
        "expected_review_digest": "a" * 64, "evidence": "Synthetic missing review",
        "acknowledge_invoice_invalidation": True}
    assert (await api.post(endpoint, json=data)).status_code == 409
    path, reviewed = await cancel_request(api, ids["org"], {
        "version": invoice["version"], "content_sha256": invoice["content_sha256"]})
    assert (await api.post(path, json={**reviewed, "expected_review_digest": "0" * 64})).status_code == 409
    assert await session.scalar(select(func.count()).select_from(InvoiceCancellationReceipt)) == 0
    doc = await session.get(DealDocument, invoice["id"])
    assert (doc.status, doc.reserve_status) == ("issued", "unreserved")


async def test_unreserved_cancellation_failure_rolls_back_and_allows_same_command(api, session, monkeypatch):
    from modules.sales.invoice_cancellation import InvoiceCancellationReceipt

    ids, invoice = await issue_unreserved(api, session)
    path, data = await cancel_request(api, ids["org"], {
        "version": invoice["version"], "content_sha256": invoice["content_sha256"]})
    bus = api._transport.app.state.core.event_bus
    original_emit = bus.emit

    def fail(current_session, event_type, payload, version=1):
        if event_type == "sales.invoice.cancelled":
            raise RuntimeError("Synthetic failure after never-reserved cancellation")
        return original_emit(current_session, event_type, payload, version)

    monkeypatch.setattr(bus, "emit", fail)
    with pytest.raises(RuntimeError, match="Synthetic failure"):
        await api.post(path, json=data)
    assert await session.scalar(select(func.count()).select_from(InvoiceCancellationReceipt)) == 0
    assert await session.scalar(select(func.count()).select_from(InvoiceReservationRelease)) == 0
    doc = await session.get(DealDocument, invoice["id"])
    assert (doc.status, doc.reserve_status) == ("issued", "unreserved")
    await session.commit()
    monkeypatch.setattr(bus, "emit", original_emit)
    assert (await api.post(path, json=data)).status_code == 201


async def test_unreserved_cancellation_allows_explicit_deal_loss_finalization(api, session):
    from tests.test_deal_loss import endpoint, resolution, submit

    api.headers["X-Expected-Principal"] = "issuer"
    ids, invoice = await issue_unreserved(api, session)
    _, loss = await submit(api, ids["org"])
    path, body = await cancel_request(api, ids["org"], {
        "version": invoice["version"], "content_sha256": invoice["content_sha256"]})
    cancelled = await api.post(path, json=body)
    assert cancelled.status_code == 201, cancelled.text
    progress = await api.get(endpoint(ids["org"], loss))
    assert progress.status_code == 200, progress.text
    assert progress.json()["ready_to_finalize"], progress.text
    response = await api.post(endpoint(ids["org"], loss, "finalize"), json=resolution(loss))
    assert response.status_code == 200, response.text
    saved = response.json()["snapshot"]["invoices"][0]["cancellation_receipt"]
    assert saved["cancellation_id"] == cancelled.json()["cancellation_id"]
    assert saved["release_id"] is None
    assert await session.scalar(select(func.count()).select_from(InvoiceReservationRelease)) == 0


async def test_unreserved_cancellation_allows_linked_replacement_with_own_issuance(api, session):
    from modules.sales.invoice_issuance import InvoiceIssuanceReceipt

    ids, base = await seed(api, session)
    base["reserve_mode"] = "on_order"
    url = f"/sales/deals/{ids['deal']}/invoice-preview"
    preview = (await api.post(url, json=base)).json()
    first = await create(api, ids, {**base, "request_key": "synthetic-replaced-on-order",
        "allocations": [], "unreserved_confirmed": True,
        "expected_document_version": preview["document_version"], "expected_basis_digest": preview["basis_digest"]})
    assert first.status_code == 201, first.text
    invoice = first.json()["document"]
    old = await session.get(DealDocument, invoice["id"])
    original = (old.original_html, old.content_sha256, old.version, old.amount)
    revision = await api.post(f"/sales/documents/{old.id}/revision", json={
        "reason": "Corrected synthetic invoice", "request_key": "synthetic-on-order-revision"})
    assert revision.status_code == 201, revision.text
    child_id = revision.json()["id"]
    child_base = {**base, "document_id": child_id}
    assert (await api.post(url, json=child_base)).status_code == 409
    path, body = await cancel_request(api, ids["org"], {
        "version": invoice["version"], "content_sha256": invoice["content_sha256"]})
    assert (await api.post(path, json=body)).status_code == 201
    preview_reply = await api.post(url, json=child_base)
    assert preview_reply.status_code == 200, preview_reply.text
    preview = preview_reply.json()
    issue = await api.post(f"/sales/documents/{child_id}/issue", json={**base,
        "request_key": "synthetic-on-order-replacement-issue", "allocations": [], "unreserved_confirmed": True,
        "expected_document_version": preview["document_version"], "expected_basis_digest": preview["basis_digest"]})
    assert issue.status_code == 200, issue.text
    assert issue.json()["document"]["supersedes_id"] == old.id
    assert issue.json()["document"]["version"] == 2
    assert issue.json()["document"]["reserve_status"] == "unreserved"
    await session.refresh(old)
    assert (old.original_html, old.content_sha256, old.version, old.amount) == original
    assert (old.status, old.reserve_status, old.superseded_by_id) == ("cancelled", "unreserved", child_id)
    assert await session.scalar(select(func.count()).select_from(InvoiceIssuanceReceipt)) == 2
    assert await session.scalar(select(func.count()).select_from(InvoiceReservationRelease)) == 0
