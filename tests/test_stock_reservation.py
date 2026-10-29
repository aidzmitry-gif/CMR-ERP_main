"""Stock is reserved as one basket; a rejected invoice leaves no side effects."""
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from core.domain.models import Counterparty, OutboxEvent, Sku
from modules.integrations.models import StockItem
from modules.integrations.stock import StockService
from modules.sales.models import Deal, DealDocument, DealItem, PriceQuote
from modules.wms.invoice_reservations import InvoiceReservation
from modules.wms.models import ReservationVersion, StockMovement
from tests.test_invoice_issuance import command, create, seed


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
    party = Counterparty(name="Buyer", unp="999999977", requisites={"address": "Synthetic buyer address"})
    session.add(party)
    await session.flush()
    deal = Deal(number="G02", title="Basket", counterparty="Buyer", counterparty_id=party.id)
    skus = [Sku(code=code, title=code, unit="шт") for code in ("A", "B")]
    session.add_all([deal, *skus])
    await session.flush()
    for sku in skus:
        session.add(DealItem(deal_id=deal.id, sku_id=sku.id, qty=2, unit_price=100))
        session.add(PriceQuote(sku_code=sku.code, counterparty="Buyer", price=100))
    session.add(StockItem(sku_code="A", qty_available=10, qty_reserved=1))
    if second_available is not None:
        session.add(StockItem(sku_code="B", qty_available=second_available, qty_reserved=0))
    await session.commit()
    return deal.id


async def _owned_basket(api, session, second_available=10):
    ids, base = await seed(api, session)
    second = Sku(code="B", title="Second basket item", unit="шт")
    session.add(second)
    await session.flush()
    item = DealItem(deal_id=ids["deal"], sku_id=second.id, qty=Decimal("2"))
    session.add(item)
    session.add(ReservationVersion(organization_id=ids["org"], source="synthetic-existing-reserve",
        version=1, sku_code=ids["code"], warehouse="W", qty=Decimal("1"),
        evidence="Previously recorded synthetic manual reservation", actor="issuer"))
    if second_available is not None:
        session.add(StockMovement(organization_id=ids["org"], sku_code=second.code,
            warehouse="W", kind="in", qty=Decimal(second_available), reason="receipt"))
    await session.flush()
    base["pricing"].append({"item_id": item.id, "unit_price_net": "100.00", "vat_rate": "20.00"})
    await session.commit()
    return ids, base


async def _reservation_quantities(session):
    return [(row.source, row.sku_code, row.qty) for row in
            (await session.scalars(select(ReservationVersion).order_by(ReservationVersion.id))).all()]


@pytest.mark.parametrize("second_available", [None, 1])
@pytest.mark.parametrize("kind", ["invoice", "order"])
async def test_issue_returns_409_without_stock_or_external_write(
    session, api, monkeypatch, second_available, kind,
):
    if kind == "invoice":
        ids, base = await _owned_basket(api, session, second_available)
        payload, _ = await command(api, ids, base)
        deal_id = ids["deal"]
        before = await _reservation_quantities(session)
    else:
        deal_id = await _sale(session, second_available=second_available)
        payload = {}
    onec = api._transport.app.state.core.services.onec
    post = AsyncMock(wraps=onec.post_document)
    monkeypatch.setattr(onec, "post_document", post)
    response = await api.post(f"/sales/deals/{deal_id}/documents", json={"kind": kind, **payload})
    assert response.status_code == 409, response.text
    post.assert_not_awaited()
    assert (await session.scalars(select(DealDocument))).all() == []
    assert (await session.scalars(select(OutboxEvent))).all() == []
    if kind == "invoice":
        assert await _reservation_quantities(session) == before
        assert (await session.scalars(select(InvoiceReservation))).all() == []
    else:
        rows = (await session.scalars(select(StockItem).order_by(StockItem.id))).all()
        assert rows[0].qty_reserved == Decimal("1")
        if second_available is not None:
            assert rows[1].qty_reserved == Decimal("0")


async def test_repeated_issue_does_not_reserve_again(session, api):
    ids, base = await _owned_basket(api, session)
    payload, _ = await command(api, ids, base, key="g02-once")
    first = await create(api, ids, payload)
    assert first.status_code == 201, first.text
    first_id = first.json()["document"]["id"]
    before = await _reservation_quantities(session)
    for _ in range(2):
        repeated = await create(api, ids, payload)
        assert repeated.status_code == 200 and repeated.json()["replayed"]
        assert repeated.json()["document"]["id"] == first_id
        assert await _reservation_quantities(session) == before
    totals = {code: sum(qty for _, sku, qty in before if sku == code) for code in (ids["code"], "B")}
    assert totals == {ids["code"]: Decimal("3"), "B": Decimal("2")}
    events = (await session.scalars(select(OutboxEvent))).all()
    assert sum(event.event_type == "sales.stock.reserved" for event in events) == 1


async def test_rejected_replacement_restores_old_reserve_and_document(session, api, monkeypatch):
    ids, base = await _owned_basket(api, session)
    original_command, _ = await command(api, ids, base)
    first = await create(api, ids, original_command)
    assert first.status_code == 201, first.text
    old_id = first.json()["document"]["id"]
    revision = await api.post(f"/sales/documents/{old_id}/revision", json={
        "reason": "More stock", "request_key": "g02-replacement",
    })
    assert revision.status_code == 201, revision.text
    new_id = revision.json()["id"]
    item = await session.scalar(select(DealItem).where(DealItem.deal_id == ids["deal"])
                                .order_by(DealItem.id.desc()))
    item.qty = Decimal("20")
    await session.commit()
    old = await session.get(DealDocument, old_id)
    old_original = old.original_html
    event_ids = list(await session.scalars(select(OutboxEvent.id).order_by(OutboxEvent.id)))
    before = await _reservation_quantities(session)
    onec = api._transport.app.state.core.services.onec
    post = AsyncMock(wraps=onec.post_document)
    monkeypatch.setattr(onec, "post_document", post)
    payload = {**original_command, "request_key": "g02-replacement-issue",
               "expected_document_version": revision.json()["version"],
               "allocations": [{**line, "qty": "20.00" if line["line_no"] == 2 else line["qty"]}
                               for line in original_command["allocations"]]}
    result = await api.post(f"/sales/documents/{new_id}/issue", json=payload)
    assert result.status_code == 409, result.text
    assert result.json()["detail"] == "Cancel and reconcile the original invoice before replacement"
    post.assert_not_awaited()
    old = await session.get(DealDocument, old_id, populate_existing=True)
    new = await session.get(DealDocument, new_id, populate_existing=True)
    assert old.reserve_status == "reserved" and old.superseded_by_id is None
    assert old.status == "issued" and old.original_html == old_original
    assert new.status == "draft" and new.issued_at is None and new.original_html is None
    assert await _reservation_quantities(session) == before
    assert list(await session.scalars(select(OutboxEvent.id).order_by(OutboxEvent.id))) == event_ids
