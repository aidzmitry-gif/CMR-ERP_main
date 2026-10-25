"""Stock is reserved as one basket; a rejected invoice leaves no side effects."""
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from core.domain.models import Counterparty, OutboxEvent, Sku
from modules.finance.models import Payment
from modules.integrations.models import StockItem
from modules.integrations.stock import StockService
from modules.sales.invoice_issuance import InvoiceIssuanceReceipt
from modules.sales.models import Deal, DealDocument, DealItem, PriceQuote
from modules.wms.invoice_reservations import InvoiceReservation
from modules.wms.models import ReservationVersion, StockMovement, Task
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
    buyer = Counterparty(name="Buyer")
    session.add(buyer)
    await session.flush()
    deal = Deal(number="G02", title="Basket", counterparty="Buyer", counterparty_id=buyer.id)
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


async def _erp_sale(api, session, *, second_available=10):
    ids, base = await seed(api, session)
    sku = Sku(code="B", title="Second basket item", unit="шт")
    session.add(sku)
    await session.flush()
    item = DealItem(deal_id=ids["deal"], sku_id=sku.id, qty=2, unit_price=100)
    session.add(item)
    if second_available is not None:
        session.add(StockMovement(organization_id=ids["org"], sku_code="B", warehouse="W",
                                  kind="in", qty=Decimal(second_available), reason="receipt"))
    session.add_all([StockItem(sku_code=ids["code"], warehouse="Mirror", qty_available=100, qty_reserved=1),
                     StockItem(sku_code="B", warehouse="Mirror", qty_available=100, qty_reserved=0)])
    await session.commit()
    base["pricing"].append({"item_id": item.id, "unit_price_net": "100.00", "vat_rate": "20.00"})
    reservation = await api.post("/wms/reservations", json={"organization_id": ids["org"],
        "source": "synthetic-existing-A", "version": 1, "sku_code": ids["code"],
        "warehouse": "W", "qty": "1.00", "evidence": "Synthetic existing reservation"})
    assert reservation.status_code == 201, reservation.text
    return ids, base


async def _state(session):
    models = (DealDocument, InvoiceIssuanceReceipt, InvoiceReservation, ReservationVersion,
              StockMovement, OutboxEvent, StockItem, Payment, Task)
    return [(await session.execute(select(model.__table__).order_by(
        *model.__table__.primary_key.columns))).mappings().all() for model in models]


async def _held(session, ids):
    return dict((await session.execute(select(ReservationVersion.sku_code,
        func.sum(ReservationVersion.qty)).where(ReservationVersion.organization_id == ids["org"])
        .group_by(ReservationVersion.sku_code))).all())


@pytest.mark.parametrize("second_available", [None, 1])
@pytest.mark.parametrize("kind", ["invoice", "order"])
async def test_issue_returns_409_without_stock_or_external_write(
    session, api, monkeypatch, second_available, kind,
):
    onec = api._transport.app.state.core.services.onec
    post = AsyncMock(wraps=onec.post_document)
    monkeypatch.setattr(onec, "post_document", post)
    if kind == "invoice":
        ids, base = await _erp_sale(api, session, second_available=second_available)
        request, _ = await command(api, ids, base)
        before = await _state(session)
        response = await create(api, ids, request)
        assert response.status_code == 409, response.text
        detail = response.json()["detail"]
        assert detail["code"] == "stock_shortage" and detail["sku_code"] == "B"
        assert detail["warehouse"] == "W" and detail["requested"] == "2.00"
        assert detail["reason"] == ("unknown_stock" if second_available is None else "insufficient_stock")
        assert detail["physical"] == (None if second_available is None else "1.00")
        assert await _state(session) == before
    else:
        deal_id = await _sale(session, second_available=second_available)
        response = await api.post(f"/sales/deals/{deal_id}/documents", json={"kind": kind})
        assert response.status_code == 409, response.text
        detail = response.json()["detail"]
        assert detail.startswith("Нет складского остатка для B" if second_available is None
                                 else "Недостаточно остатка B")
        assert (await session.scalars(select(DealDocument))).all() == []
        assert (await session.scalars(select(OutboxEvent))).all() == []
        rows = (await session.scalars(select(StockItem).order_by(StockItem.id))).all()
        assert rows[0].qty_reserved == Decimal("1")
        if second_available is not None:
            assert rows[1].qty_reserved == Decimal("0")
    post.assert_not_awaited()


async def test_repeated_issue_does_not_reserve_again(session, api, monkeypatch):
    ids, base = await _erp_sale(api, session)
    mirrors = (await session.execute(select(StockItem.__table__).order_by(StockItem.id))).mappings().all()
    services = api._transport.app.state.core.services
    post = AsyncMock(wraps=services.onec.post_document)
    monkeypatch.setattr(services.onec, "post_document", post)
    request, _ = await command(api, ids, base)
    first = await create(api, ids, request)
    assert first.status_code == 201, first.text
    doc_id = first.json()["document"]["id"]
    before = await _state(session)
    assert (await session.execute(select(StockItem.__table__).order_by(StockItem.id))).mappings().all() == mirrors
    repeated = await create(api, ids, request)
    assert repeated.status_code == 200, repeated.text
    assert repeated.json() == {**first.json(), "replayed": True}
    issued = await api.post(f"/sales/documents/{doc_id}/issue",
                            json={**request, "request_key": str(uuid4())})
    assert issued.status_code == 409, issued.text
    assert issued.json()["detail"] == "Invoice already issued; replay the original request key"
    assert await _state(session) == before
    assert await _held(session, ids) == {ids["code"]: Decimal("3"), "B": Decimal("2")}
    assert await session.scalar(select(func.count()).select_from(InvoiceIssuanceReceipt)) == 1
    assert await session.scalar(select(func.count()).select_from(InvoiceReservation)) == 1
    assert await session.scalar(select(func.count()).select_from(ReservationVersion)) == 3
    events = (await session.scalars(select(OutboxEvent))).all()
    assert sum(event.event_type == "sales.stock.reserved" for event in events) == 1
    post.assert_not_awaited()


async def test_rejected_replacement_requires_confirmed_cancellation(session, api, monkeypatch):
    ids, base = await _erp_sale(api, session)
    mirrors = (await session.execute(select(StockItem.__table__).order_by(StockItem.id))).mappings().all()
    onec = api._transport.app.state.core.services.onec
    post = AsyncMock(wraps=onec.post_document)
    monkeypatch.setattr(onec, "post_document", post)
    request, _ = await command(api, ids, base)
    first = await create(api, ids, request)
    assert first.status_code == 201, first.text
    old_id = first.json()["document"]["id"]
    revision = await api.post(f"/sales/documents/{old_id}/revision", json={
        "reason": "More stock", "request_key": "g02-replacement"})
    assert revision.status_code == 201, revision.text
    new_id = revision.json()["id"]
    item = await session.scalar(select(DealItem).where(DealItem.deal_id == ids["deal"])
                                .order_by(DealItem.id.desc()))
    item.qty = Decimal("20")
    await session.commit()
    old_original = (await session.get(DealDocument, old_id)).original_html
    before = await _state(session)
    assert (await session.execute(select(StockItem.__table__).order_by(StockItem.id))).mappings().all() == mirrors
    result = await api.post(f"/sales/documents/{new_id}/issue",
                            json={**request, "request_key": str(uuid4())})
    assert result.status_code == 409, result.text
    assert result.json()["detail"] == "Cancel and reconcile the original invoice before replacement"
    post.assert_not_awaited()
    assert await _state(session) == before
    old, new = await session.get(DealDocument, old_id), await session.get(DealDocument, new_id)
    assert old.reserve_status == "reserved" and old.superseded_by_id is None
    assert old.status == "issued" and old.original_html == old_original
    assert new.status == "draft" and new.issued_at is None and new.original_html is None
    assert await _held(session, ids) == {ids["code"]: Decimal("3"), "B": Decimal("2")}
