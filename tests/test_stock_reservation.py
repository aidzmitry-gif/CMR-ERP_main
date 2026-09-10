"""Stock is reserved as one basket; a rejected invoice leaves no side effects."""
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from core.domain.models import OutboxEvent, Sku
from modules.integrations.models import StockItem
from modules.integrations.stock import StockService
from modules.sales.models import Deal, DealDocument, DealItem, PriceQuote


async def test_reserve_groups_repeated_sku_and_keeps_first_warehouse(session):
    session.add_all([
        StockItem(sku_code="A", warehouse="First", qty_available=10, qty_reserved=2),
        StockItem(sku_code="A", warehouse="Second", qty_available=100, qty_reserved=0),
    ])
    await session.commit()

    result = await StockService().reserve(session, [
        {"sku_code": "A", "qty": 2}, {"sku_code": "A", "qty": 3},
    ])
    await session.commit()

    assert result == [{"sku_code": "A", "qty": 5.0, "warehouse": "First"}]
    rows = (await session.scalars(select(StockItem).order_by(StockItem.id))).all()
    assert [row.qty_reserved for row in rows] == [Decimal("7"), Decimal("0")]


@pytest.mark.parametrize("failure", ["missing", "insufficient", "repeated"])
async def test_rejected_basket_cannot_be_partly_committed(session, failure):
    session.add(StockItem(sku_code="A", qty_available=10, qty_reserved=1))
    if failure != "missing":
        session.add(StockItem(sku_code="B", qty_available=4, qty_reserved=1))
    await session.commit()
    items = [{"sku_code": "A", "qty": 2}, {"sku_code": "B", "qty": 4}]
    if failure == "repeated":
        items = [items[0], {"sku_code": "B", "qty": 2}, {"sku_code": "B", "qty": 2}]

    with pytest.raises(ValueError):
        await StockService().reserve(session, items)
    # Even a caller committing after a rejected basket cannot retain its first line.
    await session.commit()
    rows = (await session.scalars(select(StockItem).order_by(StockItem.id))).all()
    assert all(row.qty_reserved == Decimal("1") for row in rows)


async def test_release_reports_only_quantity_actually_released(session):
    session.add(StockItem(sku_code="A", qty_available=10, qty_reserved=3))
    await session.commit()
    service = StockService()
    result = await service.release(session, [
        {"sku_code": "A", "qty": 2}, {"sku_code": "A", "qty": 5},
    ])
    await session.commit()
    assert result == [{"sku_code": "A", "qty": 3.0, "warehouse": "Главный"}]
    assert await service.release(session, [{"sku_code": "A", "qty": 5}]) == []
    assert (await session.scalar(select(StockItem))).qty_reserved == Decimal("0")


async def _sale(session, *, second_available=10):
    deal = Deal(number="G02", title="Basket", counterparty="Buyer")
    skus = [Sku(code=code, title=code, unit="шт") for code in ("A", "B")]
    session.add_all([deal, *skus])
    await session.flush()
    for sku in skus:
        session.add(DealItem(deal_id=deal.id, sku_id=sku.id, qty=2))
        session.add(PriceQuote(sku_code=sku.code, counterparty="Buyer", price=100))
    session.add(StockItem(sku_code="A", qty_available=10, qty_reserved=1))
    if second_available is not None:
        session.add(StockItem(sku_code="B", qty_available=second_available, qty_reserved=0))
    await session.commit()
    return deal.id


@pytest.mark.parametrize("second_available", [None, 1])
@pytest.mark.parametrize("kind", ["invoice", "order"])
async def test_issue_returns_409_without_stock_or_external_write(
    session, api, monkeypatch, second_available, kind,
):
    deal_id = await _sale(session, second_available=second_available)
    onec = api._transport.app.state.core.services.onec
    post = AsyncMock(wraps=onec.post_document)
    monkeypatch.setattr(onec, "post_document", post)

    response = await api.post(f"/sales/deals/{deal_id}/documents", json={"kind": kind})

    assert response.status_code == 409, response.text
    post.assert_not_awaited()
    assert (await session.scalars(select(DealDocument))).all() == []
    assert (await session.scalars(select(OutboxEvent))).all() == []
    rows = (await session.scalars(select(StockItem).order_by(StockItem.id))).all()
    assert rows[0].qty_reserved == Decimal("1")
    if second_available is not None:
        assert rows[1].qty_reserved == Decimal("0")


async def test_repeated_issue_does_not_reserve_again(session, api):
    deal_id = await _sale(session)
    request = {"kind": "invoice", "request_key": "g02-once"}
    first = await api.post(f"/sales/deals/{deal_id}/documents", json=request)
    assert first.status_code == 201, first.text
    repeated = await api.post(f"/sales/deals/{deal_id}/documents", json=request)
    issued = await api.post(f"/sales/documents/{first.json()['id']}/issue")
    assert repeated.status_code == 201 and issued.status_code == 200
    assert repeated.json()["id"] == first.json()["id"]
    rows = (await session.scalars(select(StockItem).order_by(StockItem.id))).all()
    assert [row.qty_reserved for row in rows] == [Decimal("3"), Decimal("2")]
    events = (await session.scalars(select(OutboxEvent))).all()
    assert sum(event.event_type == "sales.stock.reserved" for event in events) == 1


async def test_rejected_replacement_restores_old_reserve_and_document(session, api, monkeypatch):
    deal_id = await _sale(session)
    first = await api.post(f"/sales/deals/{deal_id}/documents", json={"kind": "invoice"})
    assert first.status_code == 201, first.text
    old_id = first.json()["id"]
    revision = await api.post(f"/sales/documents/{old_id}/revision", json={
        "reason": "More stock", "request_key": "g02-replacement",
    })
    assert revision.status_code == 201, revision.text
    new_id = revision.json()["id"]
    item = await session.scalar(select(DealItem).where(DealItem.deal_id == deal_id)
                                .order_by(DealItem.id.desc()))
    item.qty = Decimal("20")
    await session.commit()
    old = await session.get(DealDocument, old_id)
    old_original = old.original_html
    event_ids = list(await session.scalars(select(OutboxEvent.id).order_by(OutboxEvent.id)))
    onec = api._transport.app.state.core.services.onec
    post = AsyncMock(wraps=onec.post_document)
    monkeypatch.setattr(onec, "post_document", post)

    result = await api.post(f"/sales/documents/{new_id}/issue")

    assert result.status_code == 409, result.text
    post.assert_not_awaited()
    old = await session.get(DealDocument, old_id)
    new = await session.get(DealDocument, new_id)
    assert old.reserve_status == "reserved" and old.superseded_by_id is None
    assert old.status == "posted" and old.original_html == old_original
    assert new.status == "draft" and new.issued_at is None and new.original_html is None
    rows = (await session.scalars(select(StockItem).order_by(StockItem.id))).all()
    assert [row.qty_reserved for row in rows] == [Decimal("3"), Decimal("2")]
    assert list(await session.scalars(select(OutboxEvent.id).order_by(OutboxEvent.id))) == event_ids
