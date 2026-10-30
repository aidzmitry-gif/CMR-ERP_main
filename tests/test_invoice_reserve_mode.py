"""Explicit on-order invoices preserve their choice without inventing stock."""
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import delete, select, update

from core.domain.models import OutboxEvent, Sku
from modules.integrations.models import StockItem
from modules.sales.documents import digest
from modules.sales.invoice_issuance import InvoiceIssuanceReceipt
from modules.sales.models import DealDocument, DealItem
from modules.wms.invoice_reservations import InvoiceReservation
from modules.wms.models import StockMovement
from tests.test_invoice_cancellation import cancel_request
from tests.test_invoice_issuance import command as owned_command
from tests.test_invoice_issuance import create as create_owned_invoice
from tests.test_invoice_issuance import no_issue
from tests.test_invoice_issuance import seed as owned_sale

LABEL = "Под заказ — товар не зарезервирован"


@pytest.mark.parametrize("mode", ["stock", "on_order"])
async def test_printed_deadline_matches_frozen_calendar_date(api, session, monkeypatch, mode):
    from modules.sales import documents

    ids, base = await owned_sale(api, session)
    base.update(document_date="2026-09-10", valid_until="2026-09-15")
    if mode == "stock":
        command, _ = await owned_command(api, ids, base)
    else:
        base["reserve_mode"] = "on_order"
        preview = await api.post(f"/sales/deals/{ids['deal']}/invoice-preview", json=base)
        assert preview.status_code == 200, preview.text
        basis = preview.json()
        command = {**base, "request_key": "expiry-on-order",
                   "expected_document_version": basis["document_version"],
                   "expected_basis_digest": basis["basis_digest"],
                   "allocations": [], "unreserved_confirmed": True}
    issued = await create_owned_invoice(api, ids, command)
    assert issued.status_code == 201, issued.text
    result = issued.json()["document"]
    assert result["valid_until"] == "2026-09-15"
    url = f"/sales/documents/{result['id']}/render"
    response = await api.get(url)
    assert response.status_code == 200, response.text
    original = response.text
    assert "Счёт действителен до 15.09.2026 включительно." in original
    assert "банковских дней" not in original
    monkeypatch.setenv("AIOS_INVOICE_VALID_DAYS", "30")

    def reject_rerender(*args, **kwargs):
        raise AssertionError("An issued original must not be rendered again")

    monkeypatch.setattr(documents, "render_erp_invoice", reject_rerender)
    reopened = await api.get(url)
    assert reopened.status_code == 200, reopened.text
    assert reopened.text == original
    assert digest(original) == result["content_sha256"]



async def events(session, event_type):
    return (await session.scalars(select(OutboxEvent).where(
        OutboxEvent.event_type == event_type,
    ))).all()


async def test_on_order_without_stock_is_visible_frozen_and_idempotent(api, session, monkeypatch):
    ids, base = await owned_sale(api, session)
    await session.execute(delete(StockMovement))
    await session.commit()
    services = api._transport.app.state.core.services
    reserve = AsyncMock(wraps=services.wms_reservations.reserve_invoice)
    availability = AsyncMock(wraps=services.wms_reservations.invoice_availability)
    post = AsyncMock(wraps=services.onec.post_document)
    monkeypatch.setattr(services.wms_reservations, "reserve_invoice", reserve)
    monkeypatch.setattr(services.wms_reservations, "invoice_availability", availability)
    monkeypatch.setattr(services.onec, "post_document", post)
    base["reserve_mode"] = "on_order"
    preview = await api.post(f"/sales/deals/{ids['deal']}/invoice-preview", json=base)
    assert preview.status_code == 200, preview.text
    basis = preview.json()
    command = {**base, "request_key": "on-order-first",
               "expected_document_version": basis["document_version"],
               "expected_basis_digest": basis["basis_digest"],
               "allocations": [], "unreserved_confirmed": True}
    first = await create_owned_invoice(api, ids, command)
    assert first.status_code == 201, first.text
    result = first.json()["document"]
    assert result["reserve_mode"] == "on_order" and result["reserve_status"] == "unreserved"
    assert result["status"] == "issued" and result["amount"] == 240
    doc_id = result["id"]
    doc = await session.get(DealDocument, doc_id)
    assert doc.reserved_at is None and doc.snapshot_json["reserve_mode"] == "on_order"
    rendered = await api.get(f"/sales/documents/{doc_id}/render")
    assert LABEL in rendered.text
    assert digest(rendered.text) == result["content_sha256"]
    snapshot = (await api.get(f"/sales/documents/{doc_id}/snapshot")).json()
    assert snapshot["reserve_mode"] == "on_order" and snapshot["amount"] == "240.00"
    doc.terms_json = {"reserve_mode": "stock"}
    with pytest.raises(ValueError, match="неизменяем"):
        await session.commit()
    await session.rollback()
    await session.execute(update(DealDocument).where(DealDocument.id == doc_id).values(
        terms_json={"reserve_mode": "stock"},
    ))
    await session.commit()
    repeated = await create_owned_invoice(api, ids, command)
    assert repeated.status_code == 200, repeated.text
    assert repeated.json() == {**first.json(), "replayed": True}
    assert repeated.json()["document"]["id"] == doc_id
    assert (await api.get(f"/sales/documents/{doc_id}/render")).content == rendered.content
    listed = (await api.get(f"/sales/deals/{ids['deal']}/documents")).json()
    assert listed[0]["reserve_mode"] == "on_order"
    conflict = await create_owned_invoice(api, ids, {
        **command, "reserve_mode": "stock", "unreserved_confirmed": False,
        "journal_complete": True, "evidence": "Different stock intent",
        "allocations": [{"line_no": 1, "warehouse": "W", "qty": "2.00"}],
    })
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "Issuance key already has a different request/scope"
    reserve.assert_not_awaited()
    availability.assert_not_awaited()
    post.assert_not_awaited()
    assert await events(session, "sales.stock.reserved") == []
    assert await events(session, "sales.document.posted") == []
    issued = await events(session, "sales.invoice.issued")
    assert len(issued) == 1 and issued[0].payload["amount"] == "240.00"
    assert issued[0].payload["reserve_mode"] == "on_order"
    assert issued[0].payload["reserve_status"] == "unreserved"
    assert (await session.scalars(select(StockItem))).all() == []
    assert (await session.scalars(select(StockMovement))).all() == []
    assert (await session.scalars(select(InvoiceReservation))).all() == []



@pytest.mark.parametrize("mode", [None, "stock"])
@pytest.mark.parametrize("available", [None, 1])
async def test_stock_mode_never_falls_back_to_on_order(api, session, mode, available):
    ids, base = await owned_sale(api, session, physical=str(available or 1))
    if available is None:
        await session.execute(delete(StockMovement))
        await session.commit()
    payload, _ = await owned_command(api, ids, base)
    if mode is not None:
        payload["reserve_mode"] = mode
    before = list(await session.scalars(select(StockMovement.qty).order_by(StockMovement.id)))
    result = await create_owned_invoice(api, ids, payload)
    assert result.status_code == 409, result.text
    await no_issue(session)
    assert (await session.scalars(select(OutboxEvent))).all() == []
    assert list(await session.scalars(select(StockMovement.qty).order_by(StockMovement.id))) == before


@pytest.mark.parametrize("kind", ["order", "contract"])
async def test_on_order_only_accepts_invoices_for_create_and_revision(api, session, kind):
    ids, _ = await owned_sale(api, session)
    deal_id = ids["deal"]
    response = await api.post(f"/sales/deals/{deal_id}/documents", json={
        "kind": kind, "reserve_mode": "on_order",
    })
    assert response.status_code == 422, response.text
    assert "под заказ" in response.text
    assert (await session.scalars(select(DealDocument))).all() == []
    old = DealDocument(deal_id=deal_id, kind=kind, number="LEGACY", status="posted")
    session.add(old)
    await session.commit()
    response = await api.post(f"/sales/documents/{old.id}/revision", json={
        "reason": "Change terms", "request_key": "unsupported-mode", "reserve_mode": "on_order",
    })
    assert response.status_code == 422, response.text
    assert len((await session.scalars(select(DealDocument))).all()) == 1


async def test_unknown_mode_is_422(api, session):
    ids, base = await owned_sale(api, session)
    command, _ = await owned_command(api, ids, base)
    response = await create_owned_invoice(api, ids, {**command, "reserve_mode": "auto"})
    assert response.status_code == 422
    assert any(error["loc"][-1] == "reserve_mode" for error in response.json()["detail"])



@pytest.mark.parametrize("snapshot", [None, {}, {"kind": "invoice", "items": []}])
async def test_legacy_issued_mode_is_stock_even_if_mutable_terms_say_on_order(api, session, snapshot):
    ids, _ = await owned_sale(api, session)
    deal_id = ids["deal"]
    old = DealDocument(deal_id=deal_id, kind="invoice", number="LEGACY", status="posted",
                       snapshot_json=snapshot, terms_json={"reserve_mode": "on_order"})
    session.add(old)
    await session.commit()
    listed = (await api.get(f"/sales/deals/{deal_id}/documents")).json()
    assert listed[0]["reserve_mode"] == "stock"
    revision = await api.post(f"/sales/documents/{old.id}/revision", json={
        "reason": "New terms", "request_key": "legacy-revision",
    })
    assert revision.status_code == 201, revision.text
    assert revision.json()["reserve_mode"] == "stock"


async def test_default_stock_replay_preserves_legacy_request_hash(api, session):
    ids, base = await owned_sale(api, session)
    payload, _ = await owned_command(api, ids, base, key="legacy-request")
    # Frozen pre-mode ERP shape: no reserve_mode/unreserved_confirmed fields.
    historical = {**payload, "deal_id": ids["deal"], "document_id": None,
                  "operation": "erp_invoice_issue"}
    expected_hash = digest(historical)
    first = await create_owned_invoice(api, ids, payload)
    assert first.status_code == 201, first.text
    doc_id = first.json()["document"]["id"]
    receipt = await session.get(InvoiceIssuanceReceipt, doc_id)
    assert receipt.request_hash == expected_hash
    for retry in (payload, {**payload, "reserve_mode": "stock"}):
        response = await create_owned_invoice(api, ids, retry)
        assert response.status_code == 200 and response.json()["document"]["id"] == doc_id
        assert response.json()["document"]["reserve_mode"] == "stock"
        assert response.json() == {**first.json(), "replayed": True}
    doc = await session.get(DealDocument, doc_id)
    assert LABEL not in doc.original_html
    reservation = await session.get(InvoiceReservation, doc_id)
    assert sum(Decimal(row["qty"]) for row in reservation.snapshot["allocations"]) == Decimal("2")
    assert receipt.request_hash == expected_hash
    assert len(await events(session, "sales.stock.reserved")) == 1



async def _replacement_command(api, ids, base, *, doc_id=None, key):
    if base.get("reserve_mode", "stock") == "stock":
        command, _ = await owned_command(api, ids, base, doc_id=doc_id, key=key)
        return command
    preview = await api.post(f"/sales/deals/{ids['deal']}/invoice-preview", json={
        **base, **({"document_id": doc_id} if doc_id else {}),
    })
    assert preview.status_code == 200, preview.text
    basis = preview.json()
    return {**base, "request_key": key, "expected_document_version": basis["document_version"],
            "expected_basis_digest": basis["basis_digest"], "allocations": [], "unreserved_confirmed": True}


async def _replacement_original(api, session, mode, physical="10"):
    ids, base = await owned_sale(api, session, physical=physical)
    base["reserve_mode"] = mode
    command = await _replacement_command(api, ids, base, key="replacement-original")
    response = await create_owned_invoice(api, ids, command)
    assert response.status_code == 201, response.text
    return ids, base, response.json()["document"]


async def _cancel_original(api, session, ids, original):
    await session.commit()
    path, command = await cancel_request(api, ids["org"], original)
    cancelled = await api.post(path, json=command)
    assert cancelled.status_code == 201, cancelled.text
    return cancelled.json()


async def test_revision_inherits_frozen_on_order_mode_and_conflicts_on_changed_retry(api, session):
    ids, base, old = await _replacement_original(api, session, "on_order")
    await session.execute(update(DealDocument).where(DealDocument.id == old["id"]).values(
        terms_json={"reserve_mode": "stock"},
    ))
    await session.commit()
    url = f"/sales/documents/{old['id']}/revision"
    payload = {"reason": "Revised terms", "request_key": "inherit-mode"}
    revision = await api.post(url, json=payload)
    assert revision.status_code == 201, revision.text
    new = revision.json()
    assert new["reserve_mode"] == "on_order" and new["status"] == "draft"
    replay = await api.post(url, json=payload)
    assert replay.json()["id"] == new["id"]
    conflict = await api.post(url, json={**payload, "reserve_mode": "stock"})
    assert conflict.status_code == 409
    before = await api.post(f"/sales/deals/{ids['deal']}/invoice-preview", json={**base, "document_id": new["id"]})
    assert before.status_code == 409
    await _cancel_original(api, session, ids, old)
    command = await _replacement_command(api, ids, base, doc_id=new["id"], key="inherit-mode-issue")
    issued = await api.post(f"/sales/documents/{new['id']}/issue", json=command)
    assert issued.status_code == 200 and issued.json()["document"]["reserve_status"] == "unreserved", issued.text
    assert (await session.get(DealDocument, new["id"])).snapshot_json["reserve_mode"] == "on_order"
    old_row = await session.get(DealDocument, old["id"], populate_existing=True)
    assert old_row.superseded_by_id == new["id"] and old_row.reserve_status == "unreserved"
    assert old_row.status == "cancelled"
    assert await events(session, "sales.stock.reserved") == []


async def test_revision_on_order_to_stock_is_atomic_and_retryable(api, session):
    ids, base, old = await _replacement_original(api, session, "on_order", physical="1")
    old_id = old["id"]
    original = (await api.get(f"/sales/documents/{old_id}/render")).content
    revision = await api.post(f"/sales/documents/{old_id}/revision", json={
        "reason": "Goods have arrived", "request_key": "switch-to-stock", "reserve_mode": "stock",
    })
    assert revision.status_code == 201, revision.text
    new_id = revision.json()["id"]
    await _cancel_original(api, session, ids, old)
    base["reserve_mode"] = "stock"
    command = await _replacement_command(api, ids, base, doc_id=new_id, key="switch-stock-issue")
    event_ids = list(await session.scalars(select(OutboxEvent.id).order_by(OutboxEvent.id)))
    rejected = await api.post(f"/sales/documents/{new_id}/issue", json=command)
    assert rejected.status_code == 409, rejected.text
    old_row = await session.get(DealDocument, old_id, populate_existing=True)
    new_row = await session.get(DealDocument, new_id, populate_existing=True)
    assert old_row.superseded_by_id is None and old_row.reserve_status == "unreserved"
    assert new_row.status == "draft" and new_row.reserve_mode == "stock"
    assert new_row.snapshot_json is None and new_row.original_html is None
    assert list(await session.scalars(select(OutboxEvent.id).order_by(OutboxEvent.id))) == event_ids
    session.add(StockMovement(organization_id=ids["org"], sku_code=ids["code"], warehouse="W",
        kind="in", qty=Decimal("9"), reason="receipt"))
    await session.commit()
    issued = await api.post(f"/sales/documents/{new_id}/issue", json=command)
    assert issued.status_code == 200, issued.text
    assert issued.json()["document"]["reserve_mode"] == "stock"
    assert issued.json()["document"]["reserve_status"] == "reserved"
    reservation = await session.get(InvoiceReservation, new_id)
    assert sum(Decimal(x["qty"]) for x in reservation.snapshot["allocations"]) == Decimal("2")
    assert len(await events(session, "sales.stock.reserved")) == 1
    assert (await api.get(f"/sales/documents/{old_id}/render")).content == original


async def test_revision_stock_to_on_order_releases_only_old_basket(api, session, monkeypatch):
    from modules.wms.invoice_reservations import InvoiceReservationRelease

    ids, base, old = await _replacement_original(api, session, "stock")
    original = (await api.get(f"/sales/documents/{old['id']}/render")).content
    services = api._transport.app.state.core.services
    reserve = AsyncMock(wraps=services.wms_reservations.reserve_invoice)
    monkeypatch.setattr(services.wms_reservations, "reserve_invoice", reserve)
    revision = await api.post(f"/sales/documents/{old['id']}/revision", json={
        "reason": "Customer changed product", "request_key": "switch-to-order", "reserve_mode": "on_order",
    })
    assert revision.status_code == 201, revision.text
    new_id = revision.json()["id"]
    replacement_sku = Sku(code="NEW-ORDER", title="New ordered product", unit="шт")
    session.add(replacement_sku)
    await session.flush()
    replacement_item = await session.get(DealItem, ids["item"])
    replacement_item.sku_id = replacement_sku.id
    await session.commit()
    cancelled = await _cancel_original(api, session, ids, old)
    release = await session.get(InvoiceReservationRelease, cancelled["release_id"])
    assert release.document_id == old["id"]
    assert [(line["sku_code"], Decimal(line["released_qty"])) for line in release.snapshot["lines"]] == [(ids["code"], Decimal("2"))]
    base["reserve_mode"] = "on_order"
    base["pricing"][0]["unit_price_net"] = "120.00"
    command = await _replacement_command(api, ids, base, doc_id=new_id, key="switch-on-order-issue")
    issued = await api.post(f"/sales/documents/{new_id}/issue", json=command)
    assert issued.status_code == 200, issued.text
    assert issued.json()["document"]["reserve_status"] == "unreserved"
    assert issued.json()["document"]["amount"] == 288
    old_row = await session.get(DealDocument, old["id"], populate_existing=True)
    assert old_row.reserve_status == "released" and old_row.reserve_mode == "stock"
    assert old_row.superseded_by_id == new_id
    reserve.assert_not_awaited()
    assert await session.get(InvoiceReservation, new_id) is None
    assert len(await events(session, "sales.stock.reserved")) == 1
    assert LABEL in (await api.get(f"/sales/documents/{new_id}/render")).text
    assert (await api.get(f"/sales/documents/{old['id']}/render")).content == original


async def test_stock_gateway_unavailable_requires_explicit_on_order(api, session, monkeypatch):
    ids, base = await owned_sale(api, session, physical="10")
    stock_command, _ = await owned_command(api, ids, base)
    monkeypatch.setattr(api._transport.app.state.core.services, "wms_reservations", None)
    rejected = await create_owned_invoice(api, ids, stock_command)
    assert rejected.status_code == 503, rejected.text
    await no_issue(session)
    unreserved_basis = {**base, "reserve_mode": "on_order"}
    preview = await api.post(f"/sales/deals/{ids['deal']}/invoice-preview", json=unreserved_basis)
    assert preview.status_code == 200, preview.text
    basis = preview.json()
    assert basis["availability"] is None
    result = await create_owned_invoice(api, ids, {
        **unreserved_basis, "request_key": "explicit-on-order-gateway-unavailable",
        "expected_document_version": basis["document_version"],
        "expected_basis_digest": basis["basis_digest"],
        "allocations": [], "unreserved_confirmed": True,
    })
    assert result.status_code == 201, result.text
    assert result.json()["document"]["reserve_status"] == "unreserved"
    assert await events(session, "sales.stock.reserved") == []
