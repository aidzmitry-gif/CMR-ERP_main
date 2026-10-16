import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError

from core.domain.models import OutboxEvent, User
from modules.sales.models import Deal, DealItem, DealItemRequest, PriceQuote, PriceQuoteRequest
from tests.accounting.test_postgres import pg_factory as pg_factory  # noqa: F401
from tests.integration.test_invoice_issuance_postgres import (
    issuance_pg as issuance_pg,  # noqa: F401
)
from tests.test_sales_item_requests import seed

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("conflict", [False, True])
async def test_pg_price_request_concurrency_and_immutable_receipt(issuance_pg, conflict):
    api, factory = issuance_pg
    async with factory() as session:
        conn = await session.connection()
        await conn.run_sync(lambda c: PriceQuote.__table__.create(c, checkfirst=True))
        await session.commit()
    body = {"sku_code": "PG-PRICE", "counterparty": "Synthetic", "price": "12.50", "request_key": str(uuid4())}
    results = await asyncio.gather(api.post("/sales/prices", json=body),
        api.post("/sales/prices", json={**body, "price": "13.00" if conflict else "12.50"}))
    assert sorted(r.status_code for r in results) == ([201, 409] if conflict else [201, 201]), [r.text for r in results]
    if not conflict:
        assert results[0].json() == results[1].json()
    saved = await api.get(f"/sales/price-requests/{body['request_key']}")
    assert saved.status_code == 200
    assert saved.json() == next(r.json() for r in results if r.status_code == 201)
    async with factory() as session:
        for model in (PriceQuote, PriceQuoteRequest):
            assert await session.scalar(select(func.count()).select_from(model)) == 1
        assert await session.scalar(select(func.count()).select_from(OutboxEvent).where(
            OutboxEvent.event_type == "sales.price.quoted")) == 1
    for sql in ("UPDATE sales.price_quote_request SET actor='changed'",
                "DELETE FROM sales.price_quote_request", "TRUNCATE sales.price_quote_request"):
        async with factory() as session:
            with pytest.raises(DBAPIError, match="immutable"):
                await session.execute(text(sql))
            await session.rollback()


@pytest.mark.parametrize("other_deal", [False, True])
async def test_pg_concurrent_item_key_single_effect_and_history_guards(issuance_pg, other_deal):
    api, factory = issuance_pg
    async with factory() as session:
        connection = await session.connection()
        await connection.run_sync(lambda c: PriceQuote.__table__.create(c, checkfirst=True))
        await session.commit()
        deal, sku = await seed(session)
        second_deal = Deal(number="ITEM-SECOND", title="Synthetic", counterparty="Synthetic")
        session.add(second_deal)
        await session.commit()
        target = second_deal.id if other_deal else deal
    body = {"sku_id": sku, "qty": "2.50", "request_key": str(uuid4())}
    responses = await asyncio.gather(
        api.post(f"/sales/deals/{deal}/items", json=body),
        api.post(f"/sales/deals/{target}/items", json=body),
    )
    assert sorted(row.status_code for row in responses) == ([201, 409] if other_deal else [201, 201]), [row.text for row in responses]
    if not other_deal:
        assert responses[0].json() == responses[1].json()
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(DealItem)) == 1
        assert await session.scalar(select(func.count()).select_from(DealItemRequest)) == 1
        assert await session.scalar(select(func.count()).select_from(OutboxEvent).where(
            OutboxEvent.event_type == "sales.item.changed")) == 1
    for sql in ["UPDATE sales.deal_item_request SET actor='changed'",
                "DELETE FROM sales.deal_item_request", "TRUNCATE sales.deal_item_request"]:
        async with factory() as session:
            with pytest.raises(DBAPIError, match="immutable"):
                await session.execute(text(sql))
            await session.rollback()


@pytest.mark.parametrize("replay", [False, True])
async def test_pg_item_request_rechecks_owner_after_lock_wait(issuance_pg, replay):
    api, factory = issuance_pg
    async with factory() as session:
        connection = await session.connection()
        for model in (PriceQuote, User):
            await connection.run_sync(lambda c, model=model: model.__table__.create(c, checkfirst=True))
        await session.commit()
        deal, sku = await seed(session)
        session.add(User(username="item-owner", full_name="Synthetic", employee_id=701,
                         deal_visibility="own", status="active"))
        await session.execute(update(Deal).where(Deal.id == deal).values(owner_id=701))
        await session.commit()
    body = {"sku_id": sku, "qty": "1.00", "request_key": str(uuid4())}
    path = f"/sales/deals/{deal}/items"
    if replay:
        assert (await api.post(path, json=body)).status_code == 201
    request = None
    async with factory() as holder:
        holder_pid = await holder.scalar(text("SELECT pg_backend_pid()"))
        await holder.execute(update(Deal).where(Deal.id == deal).values(owner_id=702))
        try:
            request = asyncio.create_task(api.post(path, json=body,
                headers={"X-User": "item-owner", "X-User-Roles": "sales"}))
            async with asyncio.timeout(15):
                async with factory() as observer:
                    while True:
                        if request.done():
                            response = await request
                            pytest.fail(f"Request did not wait for deal lock: {response.status_code} {response.text}")
                        # pg_stat_activity is cached within the observer transaction.
                        await observer.execute(text("SELECT pg_stat_clear_snapshot()"))
                        blocked = await observer.scalar(text(
                            "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() "
                            "AND :holder = ANY(pg_blocking_pids(pid)) AND wait_event_type='Lock'"),
                            {"holder": holder_pid})
                        if blocked:
                            break
                        await asyncio.sleep(0.02)
            await holder.commit()
            response = await asyncio.wait_for(request, 15)
            assert response.status_code == 404, response.text
        finally:
            await holder.rollback()
            if request is not None and not request.done():
                request.cancel()
                await asyncio.gather(request, return_exceptions=True)
    async with factory() as session:
        for model in (DealItem, DealItemRequest):
            assert await session.scalar(select(func.count()).select_from(model)) == int(replay)
        assert await session.scalar(select(func.count()).select_from(OutboxEvent).where(
            OutboxEvent.event_type == "sales.item.changed")) == int(replay)
