"""Explicit on-order invoices preserve their choice without inventing stock."""
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select, update

from core.domain.models import OutboxEvent, Sku
from modules.integrations.models import StockItem
from modules.sales.documents import digest
from modules.sales.models import Deal, DealDocument, DealItem, PriceQuote

LABEL = "Под заказ — товар не зарезервирован"


async def sale(session, *, available=None):
    deal = Deal(number="ON-ORDER", title="Goods on order", counterparty="Buyer")
    sku = Sku(code="ON-ORDER", title="Ordered goods", unit="шт")
    session.add_all([deal, sku])
    await session.flush()
    session.add_all([
        DealItem(deal_id=deal.id, sku_id=sku.id, qty=2),
        PriceQuote(sku_code=sku.code, counterparty="Buyer", price=100),
    ])
    if available is not None:
        session.add(StockItem(sku_code=sku.code, qty_available=available, qty_reserved=0))
    await session.commit()
    return deal.id


async def invoice(api, deal_id, mode="on_order"):
    response = await api.post(f"/sales/deals/{deal_id}/documents", json={
        "kind": "invoice", "reserve_mode": mode, "request_key": "on-order-first",
    })
    assert response.status_code == 201, response.text
    return response.json()


async def events(session, event_type):
    return (await session.scalars(select(OutboxEvent).where(
        OutboxEvent.event_type == event_type,
    ))).all()


async def test_on_order_without_stock_is_visible_frozen_and_idempotent(api, session, monkeypatch):
    deal_id = await sale(session)
    services = api._transport.app.state.core.services
    reserve = AsyncMock(wraps=services.stock.reserve)
    prelock = AsyncMock(wraps=services.stock.lock_reservation_items)
    post = AsyncMock(wraps=services.onec.post_document)
    monkeypatch.setattr(services.stock, "reserve", reserve)
    monkeypatch.setattr(services.stock, "lock_reservation_items", prelock)
    monkeypatch.setattr(services.onec, "post_document", post)
    result = await invoice(api, deal_id)
    assert result["reserve_mode"] == "on_order" and result["reserve_status"] == "unreserved"
    assert result["status"] == "posted" and result["amount"] == 240
    doc = await session.get(DealDocument, result["id"])
    assert doc.reserved_at is None and doc.snapshot_json["reserve_mode"] == "on_order"
    rendered = await api.get(f"/sales/documents/{doc.id}/render")
    assert f'<div class="order"><b>{LABEL}</b></div>' in rendered.text
    assert digest(rendered.text) == result["content_sha256"]
    snapshot = (await api.get(f"/sales/documents/{doc.id}/snapshot")).json()
    assert snapshot["reserve_mode"] == "on_order" and snapshot["amount"] == "240.00"
    doc_id = doc.id
    # The existing ORM guard also protects the newly persisted choice.
    doc.terms_json = {"reserve_mode": "stock"}
    with pytest.raises(ValueError, match="неизменяем"):
        await session.commit()
    await session.rollback()
    # Simulate out-of-band imported terms: the frozen snapshot still owns mode.
    await session.execute(update(DealDocument).where(DealDocument.id == doc_id).values(
        terms_json={"reserve_mode": "stock"},
    ))
    await session.commit()
    doc = await session.get(DealDocument, doc_id)
    assert (await invoice(api, deal_id))["id"] == doc.id
    repeated = await api.post(f"/sales/documents/{doc.id}/issue")
    assert repeated.json()["reserve_mode"] == "on_order"
    assert (await api.get(f"/sales/documents/{doc.id}/render")).content == rendered.content
    listed = (await api.get(f"/sales/deals/{deal_id}/documents")).json()
    assert listed[0]["reserve_mode"] == "on_order"
    conflict = await api.post(f"/sales/deals/{deal_id}/documents", json={
        "kind": "invoice", "reserve_mode": "stock", "request_key": "on-order-first",
    })
    assert conflict.status_code == 409
    reserve.assert_not_awaited()
    prelock.assert_not_awaited()
    post.assert_awaited_once()
    assert await events(session, "sales.stock.reserved") == []
    posted = await events(session, "sales.document.posted")
    assert len(posted) == 1 and posted[0].payload["amount"] == "240.00"
    assert posted[0].payload["reserve_mode"] == "on_order"
    assert posted[0].payload["reserve_status"] == "unreserved"
    assert (await session.scalars(select(StockItem))).all() == []


@pytest.mark.parametrize("mode", [None, "stock"])
@pytest.mark.parametrize("available", [None, 1])
async def test_stock_mode_never_falls_back_to_on_order(api, session, mode, available):
    deal_id = await sale(session, available=available)
    payload = {"kind": "invoice"}
    if mode is not None:
        payload["reserve_mode"] = mode
    result = await api.post(f"/sales/deals/{deal_id}/documents", json=payload)
    assert result.status_code == 409, result.text
    assert (await session.scalars(select(DealDocument))).all() == []
    assert (await session.scalars(select(OutboxEvent))).all() == []
    if available is not None:
        assert (await session.scalar(select(StockItem))).qty_reserved == 0


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


async def test_unknown_mode_is_422(api, session):
    deal_id = await sale(session)
    response = await api.post(f"/sales/deals/{deal_id}/documents", json={
        "kind": "invoice", "reserve_mode": "auto",
    })
    assert response.status_code == 422


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


async def test_default_stock_replay_preserves_legacy_request_hash(api, session):
    deal_id = await sale(session, available=10)
    payload = {"kind": "invoice", "request_key": "legacy-request"}
    first = await api.post(f"/sales/deals/{deal_id}/documents", json=payload)
    assert first.status_code == 201, first.text
    doc = await session.get(DealDocument, first.json()["id"])
    doc.request_hash = digest({"deal_id": deal_id, "operation": "create",
                               **payload, "requested_by": ""})
    await session.commit()
    for retry in (payload, {**payload, "reserve_mode": "stock"}):
        response = await api.post(f"/sales/deals/{deal_id}/documents", json=retry)
        assert response.status_code == 201 and response.json()["id"] == doc.id
        assert response.json()["reserve_mode"] == "stock"
    assert LABEL not in doc.original_html
    assert (await session.scalar(select(StockItem))).qty_reserved == 2
    assert len(await events(session, "sales.stock.reserved")) == 1


async def test_revision_inherits_frozen_on_order_mode_and_conflicts_on_changed_retry(api, session):
    deal_id = await sale(session)
    old = await invoice(api, deal_id)
    old_row = await session.get(DealDocument, old["id"])
    # A mismatched draft-terms import must not override the issued snapshot.
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
    issued = await api.post(f"/sales/documents/{new['id']}/issue")
    assert issued.status_code == 200 and issued.json()["reserve_status"] == "unreserved"
    assert (await session.get(DealDocument, new["id"])).snapshot_json["reserve_mode"] == "on_order"
    assert old_row.superseded_by_id == new["id"] and old_row.reserve_status == "unreserved"
    assert await events(session, "sales.stock.reserved") == []


async def test_revision_on_order_to_stock_is_atomic_and_retryable(api, session):
    deal_id = await sale(session)
    old = await invoice(api, deal_id)
    old_id = old["id"]
    original = (await api.get(f"/sales/documents/{old_id}/render")).content
    revision = await api.post(f"/sales/documents/{old_id}/revision", json={
        "reason": "Goods have arrived", "request_key": "switch-to-stock", "reserve_mode": "stock",
    })
    assert revision.status_code == 201, revision.text
    new_id = revision.json()["id"]
    event_ids = list(await session.scalars(select(OutboxEvent.id).order_by(OutboxEvent.id)))
    rejected = await api.post(f"/sales/documents/{new_id}/issue")
    assert rejected.status_code == 409, rejected.text
    old_row, new_row = await session.get(DealDocument, old_id), await session.get(DealDocument, new_id)
    assert old_row.superseded_by_id is None and old_row.reserve_status == "unreserved"
    assert new_row.status == "draft" and new_row.reserve_mode == "stock"
    assert new_row.snapshot_json is None and new_row.original_html is None
    assert list(await session.scalars(select(OutboxEvent.id).order_by(OutboxEvent.id))) == event_ids
    session.add(StockItem(sku_code="ON-ORDER", qty_available=10, qty_reserved=0))
    await session.commit()
    issued = await api.post(f"/sales/documents/{new_id}/issue")
    assert issued.status_code == 200, issued.text
    assert issued.json()["reserve_mode"] == "stock" and issued.json()["reserve_status"] == "reserved"
    assert (await session.scalar(select(StockItem))).qty_reserved == Decimal("2")
    assert len(await events(session, "sales.stock.reserved")) == 1
    assert (await api.get(f"/sales/documents/{old_id}/render")).content == original


async def test_revision_stock_to_on_order_releases_only_old_basket(api, session, monkeypatch):
    deal_id = await sale(session, available=10)
    old = await invoice(api, deal_id, "stock")
    services = api._transport.app.state.core.services
    reserve = AsyncMock(wraps=services.stock.reserve)
    prelock = AsyncMock(wraps=services.stock.lock_reservation_items)
    monkeypatch.setattr(services.stock, "reserve", reserve)
    monkeypatch.setattr(services.stock, "lock_reservation_items", prelock)
    revision = await api.post(f"/sales/documents/{old['id']}/revision", json={
        "reason": "Customer changed product", "request_key": "switch-to-order", "reserve_mode": "on_order",
    })
    assert revision.status_code == 201, revision.text
    new_id = revision.json()["id"]
    # Replacement has a wholly different SKU with no stock row.
    replacement_sku = Sku(code="NEW-ORDER", title="New ordered product", unit="шт")
    session.add(replacement_sku)
    await session.flush()
    (await session.scalar(select(DealItem))).sku_id = replacement_sku.id
    session.add(PriceQuote(sku_code="NEW-ORDER", counterparty="Buyer", price=120))
    await session.commit()
    issued = await api.post(f"/sales/documents/{new_id}/issue")
    assert issued.status_code == 200, issued.text
    assert issued.json()["reserve_status"] == "unreserved" and issued.json()["amount"] == 288
    assert (await session.scalar(select(StockItem))).qty_reserved == 0
    old_row = await session.get(DealDocument, old["id"])
    assert old_row.reserve_status == "released" and old_row.reserve_mode == "stock"
    assert old_row.superseded_by_id == new_id
    reserve.assert_not_awaited()
    prelock.assert_awaited_once()
    assert prelock.call_args.args[1] == [{"sku_code": "ON-ORDER", "qty": "2.00"}]
    assert len(await events(session, "sales.stock.reserved")) == 1
    assert LABEL in (await api.get(f"/sales/documents/{new_id}/render")).text


async def test_stock_gateway_unavailable_requires_explicit_on_order(api, session, monkeypatch):
    deal_id = await sale(session)
    monkeypatch.setattr(api._transport.app.state.core.services, "stock", None)
    rejected = await api.post(f"/sales/deals/{deal_id}/documents", json={"kind": "invoice"})
    assert rejected.status_code == 503, rejected.text
    assert (await session.scalars(select(DealDocument))).all() == []
    assert (await invoice(api, deal_id))["reserve_status"] == "unreserved"
