"""Explicit ERP supply modes preserve originals and require reconciled replacements."""
from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal
from hashlib import sha256
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select, update

from core.domain.models import OutboxEvent, Sku
from modules.finance.models import Payment
from modules.integrations.models import StockItem
from modules.sales.documents import digest
from modules.sales.invoice_cancellation import InvoiceCancellationReceipt
from modules.sales.invoice_issuance import InvoiceIssuanceReceipt, canonical_request
from modules.sales.models import Deal, DealDocument, DealItem, PriceQuote
from modules.sales.reservation_source import SalesReservationSource
from modules.sales.schemas import InvoiceCreate
from modules.wms.invoice_reservations import InvoiceReservation, InvoiceReservationRelease
from modules.wms.models import ReservationVersion, StockMovement, Task
from tests.test_invoice_cancellation import cancel_request
from tests.test_invoice_issuance import command as stock_command
from tests.test_invoice_issuance import create, seed

LABEL = "Под заказ — товар не зарезервирован"


async def sale(session, *, available=None):
    deal = Deal(number="ON-ORDER", title="Goods on order", counterparty="Buyer")
    sku = Sku(code="ON-ORDER", title="Ordered goods", unit="шт")
    session.add_all([deal, sku])
    await session.flush()
    session.add_all([
        DealItem(deal_id=deal.id, sku_id=sku.id, qty=2, unit_price=100),
        PriceQuote(sku_code=sku.code, counterparty="Buyer", price=100),
    ])
    if available is not None:
        session.add(StockItem(sku_code=sku.code, qty_available=available, qty_reserved=0))
    await session.commit()
    return deal.id



async def events(session, event_type):
    return (await session.scalars(select(OutboxEvent).where(
        OutboxEvent.event_type == event_type,
    ))).all()



@pytest.mark.parametrize("kind", ["order", "contract"])
async def test_on_order_only_accepts_invoices_for_create_and_revision(api, session, kind):
    deal_id = await sale(session)
    response = await api.post(f"/sales/deals/{deal_id}/documents", json={
        "kind": kind, "reserve_mode": "on_order",
    })
    assert response.status_code == 422, response.text
    assert (await session.scalars(select(DealDocument))).all() == []
    old = DealDocument(deal_id=deal_id, kind=kind, number="LEGACY", status="posted")
    session.add(old)
    await session.commit()
    response = await api.post(f"/sales/documents/{old.id}/revision", json={
        "reason": "Change terms", "request_key": "unsupported-mode", "reserve_mode": "on_order",
    })
    assert response.status_code == 422, response.text
    assert len((await session.scalars(select(DealDocument))).all()) == 1



@pytest.mark.parametrize("snapshot", [None, {}, {"kind": "invoice", "items": []}])
async def test_legacy_issued_mode_is_stock_even_if_mutable_terms_say_on_order(api, session, snapshot):
    deal_id = await sale(session)
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



async def _erp_sale(api, session, *, available=None, mirror=False):
    ids, base = await seed(api, session, physical=str(available) if available is not None else "10")
    if available is None:
        await session.execute(delete(StockMovement).where(StockMovement.organization_id == ids["org"]))
    if mirror:
        session.add(StockItem(sku_code=ids["code"], qty_available=100, qty_reserved=0))
    await session.commit()
    base.update(document_date=date.today().isoformat(), valid_until=(date.today() + timedelta(days=5)).isoformat())
    return ids, base


async def _request(api, ids, base, mode=None, *, doc_id=None, key=None):
    key = key or str(uuid4())
    if mode != "on_order":
        body = {**base, **({"reserve_mode": mode} if mode is not None else {})}
        command, _ = await stock_command(api, ids, body, doc_id=doc_id, key=key)
        return command
    body = {**base, "reserve_mode": "on_order"}
    preview = await api.post(f"/sales/deals/{ids['deal']}/invoice-preview",
                             json={**body, **({"document_id": doc_id} if doc_id is not None else {})})
    assert preview.status_code == 200, preview.text
    facts = preview.json()
    assert facts["availability"] is None
    return {**body, "request_key": key, "expected_document_version": facts["document_version"],
            "expected_basis_digest": facts["basis_digest"], "allocations": [], "unreserved_confirmed": True}


async def _issue(api, ids, base, mode="on_order"):
    command = await _request(api, ids, base, mode)
    response = await create(api, ids, command)
    assert response.status_code == 201, response.text
    return response.json()["document"], command


async def _state(session):
    models = (DealDocument, InvoiceIssuanceReceipt, InvoiceReservation, ReservationVersion,
              StockMovement, OutboxEvent, StockItem, Payment, Task)
    return [(await session.execute(select(model.__table__).order_by(
        *model.__table__.primary_key.columns))).mappings().all() for model in models]


async def _cancel(api, session, ids, document):
    assert document["id"] == 1
    facts = await SalesReservationSource().invoice_shipping_source(session, document["id"],
        organization_id=ids["org"], expected_version=document["version"],
        expected_content_sha256=document["content_sha256"], operation="cancellation")
    await session.commit()
    path, body = await cancel_request(api, ids["org"], facts)
    response = await api.post(path, json=body)
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "cancelled"
    assert await session.scalar(select(func.count()).select_from(InvoiceCancellationReceipt)) == 1


@pytest.mark.parametrize("mode", ["stock", "on_order"])
async def test_printed_deadline_matches_frozen_calendar_date(api, session, monkeypatch, mode):
    monkeypatch.setenv("AIOS_INVOICE_VALID_DAYS", "5")
    ids, base = await _erp_sale(api, session, available=10)
    base.update(document_date="2026-09-10", valid_until="2026-09-15")
    result, _ = await _issue(api, ids, base, mode)
    assert result["valid_until"] == "2026-09-15"
    url = f"/sales/documents/{result['id']}/render"
    original = (await api.get(url)).text
    assert "Действителен до 2026-09-15." in original
    assert "банковских дней" not in original
    monkeypatch.setenv("AIOS_INVOICE_VALID_DAYS", "30")
    assert (await api.get(url)).text == original


async def test_on_order_without_stock_is_visible_frozen_and_idempotent(api, session, monkeypatch):
    ids, base = await _erp_sale(api, session)
    services = api._transport.app.state.core.services
    reserve = AsyncMock(wraps=services.stock.reserve)
    prelock = AsyncMock(wraps=services.stock.lock_reservation_items)
    post = AsyncMock(wraps=services.onec.post_document)
    wms_reserve = AsyncMock(wraps=services.wms_reservations.reserve_invoice)
    monkeypatch.setattr(services.stock, "reserve", reserve)
    monkeypatch.setattr(services.stock, "lock_reservation_items", prelock)
    monkeypatch.setattr(services.onec, "post_document", post)
    monkeypatch.setattr(services.wms_reservations, "reserve_invoice", wms_reserve)
    result, command = await _issue(api, ids, base)
    assert result["reserve_mode"] == "on_order" and result["reserve_status"] == "unreserved"
    assert result["status"] == "issued" and result["amount"] == 240
    doc_id = result["id"]
    doc = await session.get(DealDocument, doc_id)
    assert doc.reserved_at is None and doc.snapshot_json["reserve_mode"] == "on_order"
    assert (await session.get(InvoiceIssuanceReceipt, doc_id)).reservation_digest is None
    rendered = await api.get(f"/sales/documents/{doc_id}/render")
    assert LABEL in rendered.text
    assert sha256(rendered.content).hexdigest() == result["content_sha256"]
    snapshot = (await api.get(f"/sales/documents/{doc_id}/snapshot")).json()
    assert snapshot["reserve_mode"] == "on_order" and snapshot["amount"] == "240.00"
    doc.terms_json = {"reserve_mode": "stock"}
    with pytest.raises(ValueError, match="неизменяем"):
        await session.commit()
    await session.rollback()
    await session.execute(update(DealDocument).where(DealDocument.id == doc_id).values(
        terms_json={"reserve_mode": "stock"}))
    await session.commit()
    repeated = await create(api, ids, command)
    assert repeated.status_code == 200 and repeated.json()["replayed"]
    assert repeated.json()["document"]["id"] == doc_id
    issued = await api.post(f"/sales/documents/{doc_id}/issue", json={**command, "request_key": str(uuid4())})
    assert issued.status_code == 409, issued.text
    assert issued.json()["detail"] == "Invoice already issued; replay the original request key"
    assert (await api.get(f"/sales/documents/{doc_id}/render")).content == rendered.content
    assert (await api.get(f"/sales/deals/{ids['deal']}/documents")).json()[0]["reserve_mode"] == "on_order"
    conflict = await create(api, ids, {**command, "reserve_mode": "stock", "unreserved_confirmed": False,
        "allocations": [{"line_no": 1, "warehouse": "W", "qty": "2.00"}],
        "journal_complete": True, "evidence": "Synthetic changed mode"})
    assert conflict.status_code == 409, conflict.text
    reserve.assert_not_awaited()
    prelock.assert_not_awaited()
    post.assert_not_awaited()
    wms_reserve.assert_not_awaited()
    assert await events(session, "sales.stock.reserved") == []
    issued_events = await events(session, "sales.invoice.issued")
    assert len(issued_events) == 1 and issued_events[0].payload["amount"] == "240.00"
    assert issued_events[0].payload["reserve_mode"] == "on_order"
    assert await events(session, "sales.document.posted") == []
    assert await session.scalar(select(func.count()).select_from(InvoiceReservation)) == 0
    assert await session.scalar(select(func.count()).select_from(ReservationVersion)) == 0
    assert (await session.scalars(select(StockItem))).all() == []
    assert (await session.scalars(select(StockMovement))).all() == []


@pytest.mark.parametrize("mode", [None, "stock"])
@pytest.mark.parametrize("available", [None, 1])
async def test_stock_mode_never_falls_back_to_on_order(api, session, mode, available):
    ids, base = await _erp_sale(api, session, available=available, mirror=True)
    body = await _request(api, ids, base, mode)
    before = await _state(session)
    result = await create(api, ids, body)
    assert result.status_code == 409, result.text
    detail = result.json()["detail"]
    assert detail["code"] == "stock_shortage" and detail["sku_code"] == ids["code"]
    assert detail["reason"] == ("unknown_stock" if available is None else "insufficient_stock")
    assert await _state(session) == before


async def test_unknown_mode_is_422(api, session):
    ids, base = await _erp_sale(api, session, available=10)
    body = await _request(api, ids, base)
    before = await _state(session)
    response = await create(api, ids, {**body, "reserve_mode": "auto"})
    assert response.status_code == 422, response.text
    assert any(error["loc"][-1] == "reserve_mode" for error in response.json()["detail"])
    assert await _state(session) == before


async def test_default_stock_replay_preserves_legacy_request_hash(api, session):
    ids, base = await _erp_sale(api, session, available=10)
    body = await _request(api, ids, base)
    historical = deepcopy(body)
    historical.update(operation="erp_invoice_issue", deal_id=ids["deal"], document_id=None)
    historical["pricing"] = sorted(historical["pricing"], key=lambda row: row["item_id"])
    historical["allocations"] = sorted(historical["allocations"], key=lambda row: (row["line_no"], row["warehouse"]))
    data = InvoiceCreate.model_validate({"kind": "invoice", **body})
    assert digest(canonical_request(ids["deal"], None, data)) == digest(historical)
    first = await create(api, ids, body)
    assert first.status_code == 201, first.text
    doc_id = first.json()["document"]["id"]
    before = await _state(session)
    for retry in (body, {**body, "reserve_mode": "stock"}):
        response = await create(api, ids, retry)
        assert response.status_code == 200 and response.json()["document"]["id"] == doc_id
        assert response.json()["replayed"] and response.json()["document"]["reserve_mode"] == "stock"
    assert await _state(session) == before
    assert LABEL not in (await session.get(DealDocument, doc_id)).original_html
    assert await session.scalar(select(func.count()).select_from(InvoiceIssuanceReceipt)) == 1
    assert await session.scalar(select(ReservationVersion.qty)) == Decimal("2")
    assert len(await events(session, "sales.stock.reserved")) == 1


async def test_revision_inherits_frozen_on_order_mode_and_conflicts_on_changed_retry(api, session):
    ids, base = await _erp_sale(api, session)
    old, _ = await _issue(api, ids, base)
    old_id = old["id"]
    await session.execute(update(DealDocument).where(DealDocument.id == old_id).values(terms_json={"reserve_mode": "stock"}))
    await session.commit()
    url = f"/sales/documents/{old_id}/revision"
    payload = {"reason": "Revised terms", "request_key": "inherit-mode"}
    revision = await api.post(url, json=payload)
    assert revision.status_code == 201, revision.text
    new = revision.json()
    assert new["reserve_mode"] == "on_order" and new["status"] == "draft"
    assert (await api.post(url, json=payload)).json()["id"] == new["id"]
    assert (await api.post(url, json={**payload, "reserve_mode": "stock"})).status_code == 409
    await _cancel(api, session, ids, old)
    command = await _request(api, ids, base, "on_order", doc_id=new["id"])
    issued = await api.post(f"/sales/documents/{new['id']}/issue", json=command)
    assert issued.status_code == 200, issued.text
    assert issued.json()["document"]["reserve_status"] == "unreserved"
    assert (await session.get(DealDocument, new["id"])).snapshot_json["reserve_mode"] == "on_order"
    old_row = await session.get(DealDocument, old_id)
    assert old_row.status == "cancelled" and old_row.superseded_by_id == new["id"]
    assert old_row.reserve_status == "unreserved"
    assert await events(session, "sales.stock.reserved") == []


async def test_revision_on_order_to_stock_is_atomic_and_retryable(api, session):
    ids, base = await _erp_sale(api, session)
    old, _ = await _issue(api, ids, base)
    old_id = old["id"]
    original = (await api.get(f"/sales/documents/{old_id}/render")).content
    revision = await api.post(f"/sales/documents/{old_id}/revision", json={
        "reason": "Goods have arrived", "request_key": "switch-to-stock", "reserve_mode": "stock"})
    assert revision.status_code == 201, revision.text
    new_id = revision.json()["id"]
    await _cancel(api, session, ids, old)
    command = await _request(api, ids, base, "stock", doc_id=new_id)
    before = await _state(session)
    rejected = await api.post(f"/sales/documents/{new_id}/issue", json=command)
    assert rejected.status_code == 409, rejected.text
    assert rejected.json()["detail"]["code"] == "stock_shortage"
    assert rejected.json()["detail"]["reason"] == "unknown_stock"
    assert await _state(session) == before
    session.add(StockMovement(organization_id=ids["org"], sku_code=ids["code"], warehouse="W",
                              kind="in", qty=Decimal("10"), reason="receipt"))
    await session.commit()
    issued = await api.post(f"/sales/documents/{new_id}/issue", json=command)
    assert issued.status_code == 200, issued.text
    assert issued.json()["document"]["reserve_mode"] == "stock"
    assert issued.json()["document"]["reserve_status"] == "reserved"
    assert await session.scalar(select(ReservationVersion.qty)) == Decimal("2")
    assert len(await events(session, "sales.stock.reserved")) == 1
    assert (await api.get(f"/sales/documents/{old_id}/render")).content == original


async def test_revision_stock_to_on_order_releases_only_old_basket(api, session, monkeypatch):
    ids, base = await _erp_sale(api, session, available=10)
    manual = await api.post("/wms/reservations", json={"organization_id": ids["org"],
        "source": "unrelated-reserve", "version": 1, "sku_code": ids["code"],
        "warehouse": "W", "qty": "1.00", "evidence": "Synthetic unrelated basket"})
    assert manual.status_code == 201, manual.text
    old, _ = await _issue(api, ids, base, "stock")
    original = (await api.get(f"/sales/documents/{old['id']}/render")).content
    revision = await api.post(f"/sales/documents/{old['id']}/revision", json={
        "reason": "Customer changed product", "request_key": "switch-to-order", "reserve_mode": "on_order"})
    assert revision.status_code == 201, revision.text
    new_id = revision.json()["id"]
    await _cancel(api, session, ids, old)
    summary = await api.get("/wms/reservations/summary", params={"organization_id": ids["org"]})
    assert summary.status_code == 200 and summary.json()[0]["qty"] == "1.00"
    history_params = {"organization_id": ids["org"], "source": "unrelated-reserve"}
    history = await api.get("/wms/reservations/history", params=history_params)
    assert history.status_code == 200 and history.json() == [manual.json()]
    assert await session.scalar(select(func.count()).select_from(InvoiceReservationRelease)) == 1
    release = await session.scalar(select(InvoiceReservationRelease))
    assert release.document_id == old["id"] and release.organization_id == ids["org"]
    replacement = Sku(code="NEW-ORDER", title="New ordered product", unit="шт")
    session.add(replacement)
    await session.flush()
    item = await session.scalar(select(DealItem).where(DealItem.id == ids["item"]))
    item.sku_id, item.unit_price = replacement.id, Decimal("120")
    await session.commit()
    revised_base = {**base, "pricing": [{"item_id": item.id, "unit_price_net": "120.00", "vat_rate": "20.00"}]}
    services = api._transport.app.state.core.services
    reserve = AsyncMock(wraps=services.wms_reservations.reserve_invoice)
    post = AsyncMock(wraps=services.onec.post_document)
    monkeypatch.setattr(services.wms_reservations, "reserve_invoice", reserve)
    monkeypatch.setattr(services.onec, "post_document", post)
    command = await _request(api, ids, revised_base, "on_order", doc_id=new_id)
    issued = await api.post(f"/sales/documents/{new_id}/issue", json=command)
    assert issued.status_code == 200, issued.text
    assert issued.json()["document"]["reserve_status"] == "unreserved"
    assert issued.json()["document"]["amount"] == 288
    assert (await api.get("/wms/reservations/summary", params={"organization_id": ids["org"]})).json() == summary.json()
    history = await api.get("/wms/reservations/history", params=history_params)
    assert history.status_code == 200 and history.json() == [manual.json()]
    old_row = await session.get(DealDocument, old["id"])
    assert old_row.status == "cancelled" and old_row.reserve_status == "released"
    assert old_row.reserve_mode == "stock" and old_row.superseded_by_id == new_id
    reserve.assert_not_awaited()
    post.assert_not_awaited()
    assert len(await events(session, "sales.stock.reserved")) == 1
    assert LABEL in (await api.get(f"/sales/documents/{new_id}/render")).text
    assert (await api.get(f"/sales/documents/{old['id']}/render")).content == original


async def test_stock_gateway_unavailable_requires_explicit_on_order(api, session, monkeypatch):
    ids, base = await _erp_sale(api, session)
    body = await _request(api, ids, base)
    monkeypatch.setattr(api._transport.app.state.core.services, "wms_reservations", None)
    before = await _state(session)
    rejected = await create(api, ids, body)
    assert rejected.status_code == 503, rejected.text
    assert await _state(session) == before
    result, _ = await _issue(api, ids, base)
    assert result["reserve_status"] == "unreserved"
