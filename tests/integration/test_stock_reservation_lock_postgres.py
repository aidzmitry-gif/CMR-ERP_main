"""Actual row-lock contention in disposable metadata on the dedicated G02 database."""
import asyncio
import os
from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.schema import CreateSchema, DropSchema

from core.db.base import Base
from core.domain.models import OutboxEvent, Sku
from core.runtime.app import create_app
from core.runtime.deps import get_session
from modules.integrations.models import StockItem
from modules.integrations.stock import StockService
from modules.sales.models import Deal, DealDocument, DealItem, PriceQuote
from tests.integration.joint_postgres import is_joint_test_url


@pytest_asyncio.fixture
async def stock_factory():
    raw_url = os.environ.get("CRM_READY_G02_DATABASE_URL")
    if not raw_url:
        pytest.skip("Set CRM_READY_G02_DATABASE_URL to the isolated G02 PostgreSQL")
    url = make_url(raw_url)
    if (url.host, url.port, url.database) != ("127.0.0.1", 15439, "crm_ready_g02") and not is_joint_test_url(url):
        pytest.fail("G02 tests require their dedicated loopback database on port 15439")
    schema = f"g02_stock_{uuid4().hex}"
    engine = create_async_engine(url).execution_options(
        schema_translate_map={table.schema: schema for table in Base.metadata.tables.values()},
    )
    try:
        async with engine.begin() as conn:
            await conn.execute(CreateSchema(schema))
            await conn.run_sync(StockItem.__table__.create)
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        async with engine.begin() as conn:
            await conn.execute(DropSchema(schema, cascade=True, if_exists=True))
        await engine.dispose()


async def _assert_blocked(factory, holder_pid, waiter_pid, task):
    async with asyncio.timeout(10), factory() as observer:
        while not task.done():
            blocked = await observer.scalar(text(
                "SELECT :holder = ANY(pg_blocking_pids(:waiter))",
            ), {"holder": holder_pid, "waiter": waiter_pid})
            if blocked:
                return
            await asyncio.sleep(0.02)
    pytest.fail("The competing transaction did not wait on the stock row lock")


@pytest.mark.parametrize("first_operation", ["reserve", "release"])
async def test_stock_waiter_refreshes_stale_balance(stock_factory, first_operation):
    service = StockService()
    initial = 0 if first_operation == "reserve" else 7
    async with stock_factory() as setup:
        row = StockItem(sku_code="SHARED", qty_available=10, qty_reserved=initial)
        setup.add(row)
        await setup.commit()
        stock_id = row.id
    task = None
    try:
        async with stock_factory() as holder, stock_factory() as waiter:
            stale = await waiter.get(StockItem, stock_id)
            assert stale.qty_reserved == initial
            waiter_pid = await waiter.scalar(text("SELECT pg_backend_pid()"))
            holder_pid = await holder.scalar(text("SELECT pg_backend_pid()"))
            if first_operation == "reserve":
                await service.reserve(holder, [{"sku_code": "SHARED", "qty": 7}])
            else:
                await service.release(holder, [{"sku_code": "SHARED", "qty": 3}])
            # Flush is part of the same uncommitted transaction; locks remain held.
            await holder.flush()

            async def compete():
                try:
                    result = await service.reserve(waiter, [{
                        "sku_code": "SHARED", "qty": 7 if first_operation == "reserve" else 5,
                    }])
                    await waiter.commit()
                    return result
                except ValueError:
                    await waiter.rollback()
                    return "insufficient"

            task = asyncio.create_task(compete())
            await _assert_blocked(stock_factory, holder_pid, waiter_pid, task)
            assert not task.done()
            await holder.commit()
            result = await asyncio.wait_for(task, 10)
            if first_operation == "reserve":
                assert result == "insufficient"
            else:
                assert result == [{"sku_code": "SHARED", "qty": 5.0, "warehouse": "Главный"}]

        async with stock_factory() as check:
            row = await check.get(StockItem, stock_id)
            assert row.qty_reserved == Decimal("7" if first_operation == "reserve" else "9")
            assert row.qty_reserved <= row.qty_available
    finally:
        if task is not None:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def test_replacement_and_new_invoice_lock_old_and_new_stock_before_release(
    stock_factory, monkeypatch,
):
    """HIGH -> LOW replacement must not deadlock a concurrent LOW+HIGH invoice."""
    engine = stock_factory.kw["bind"]
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    app = create_app()
    app.state.core.services.db.engine = engine
    app.state.core.services.db.session_factory = stock_factory
    backend_pids = {}
    request_started = asyncio.Event()
    watch_path = None

    async def own_session(request: Request):
        async with stock_factory() as session:
            backend_pids[request.url.path] = await session.scalar(text("SELECT pg_backend_pid()"))
            if request.url.path == watch_path:
                request_started.set()
            yield session

    app.dependency_overrides[get_session] = own_session
    async with stock_factory() as setup:
        low, high = [Sku(code=code, title=code, unit="шт") for code in ("LOW", "HIGH")]
        old_deal = Deal(number="REPLACE", title="Replacement", counterparty="Buyer")
        other_deal = Deal(number="COMPETE", title="New invoice", counterparty="Buyer")
        setup.add_all([low, high, old_deal, other_deal])
        await setup.flush()
        # Stock IDs define lock order independently of SKU spelling.
        setup.add(StockItem(sku_code="LOW", qty_available=10, qty_reserved=0))
        await setup.flush()
        setup.add(StockItem(sku_code="HIGH", qty_available=10, qty_reserved=0))
        old_item = DealItem(deal_id=old_deal.id, sku_id=high.id, qty=2, unit_price=100)
        setup.add_all([
            old_item,
            DealItem(deal_id=other_deal.id, sku_id=low.id, qty=2, unit_price=100),
            DealItem(deal_id=other_deal.id, sku_id=high.id, qty=2, unit_price=100),
            PriceQuote(sku_code="LOW", counterparty="Buyer", price=100),
            PriceQuote(sku_code="HIGH", counterparty="Buyer", price=100),
        ])
        await setup.commit()
        old_deal_id, other_deal_id, item_id, low_id = (
            old_deal.id, other_deal.id, old_item.id, low.id,
        )

    tasks = []
    continue_replacement = asyncio.Event()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test",
                           headers={"X-User-Roles": "director"}) as api:
        issued = await api.post(f"/sales/deals/{old_deal_id}/documents", json={"kind": "invoice"})
        assert issued.status_code == 201, issued.text
        old_id = issued.json()["id"]
        revision = await api.post(f"/sales/documents/{old_id}/revision", json={
            "reason": "Use LOW instead of HIGH", "request_key": "g02-lock-union",
        })
        assert revision.status_code == 201, revision.text
        replacement_id = revision.json()["id"]
        async with stock_factory() as edit:
            item = await edit.get(DealItem, item_id)
            item.sku_id, item.qty = low_id, Decimal("3")
            old_original = (await edit.get(DealDocument, old_id)).original_html
            await edit.commit()

        released_old = asyncio.Event()
        stock = app.state.core.services.stock
        original_release = stock.release

        async def pause_after_release(session, items):
            result = await original_release(session, items)
            await session.flush()
            released_old.set()
            await asyncio.wait_for(continue_replacement.wait(), 10)
            return result

        monkeypatch.setattr(stock, "release", pause_after_release)
        replacement_path = f"/sales/documents/{replacement_id}/issue"
        watch_path = f"/sales/deals/{other_deal_id}/documents"
        try:
            replacement = asyncio.create_task(api.post(replacement_path))
            tasks.append(replacement)
            await asyncio.wait_for(released_old.wait(), 10)
            competing = asyncio.create_task(api.post(watch_path, json={"kind": "invoice"}))
            tasks.append(competing)
            await asyncio.wait_for(request_started.wait(), 10)
            await _assert_blocked(stock_factory, backend_pids[replacement_path],
                                  backend_pids[watch_path], competing)
            continue_replacement.set()
            responses = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), 10)
            outcomes = [getattr(getattr(result, "orig", None), "sqlstate", None)
                        if isinstance(result, Exception) else result.status_code for result in responses]
            assert outcomes == [200, 201], responses
            other_id = responses[1].json()["id"]
        finally:
            continue_replacement.set()
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async with stock_factory() as check:
        rows = (await check.scalars(select(StockItem).order_by(StockItem.id))).all()
        assert [(row.sku_code, row.qty_reserved) for row in rows] == [
            ("LOW", Decimal("5")), ("HIGH", Decimal("2")),
        ]
        old = await check.get(DealDocument, old_id)
        assert old.original_html == old_original and old.reserve_status == "released"
        assert old.superseded_by_id == replacement_id
        for doc_id in (replacement_id, other_id):
            doc = await check.get(DealDocument, doc_id)
            assert doc.status == "posted" and doc.reserve_status == "reserved"
        posted = (await check.scalars(select(OutboxEvent).where(
            OutboxEvent.event_type == "sales.document.posted",
        ))).all()
        assert len(posted) == 3


async def test_release_waits_for_reserve_without_losing_new_quantity(stock_factory):
    service = StockService()
    async with stock_factory() as setup:
        row = StockItem(sku_code="SHARED", qty_available=10, qty_reserved=7)
        setup.add(row)
        await setup.commit()
        stock_id = row.id
    task = None
    try:
        async with stock_factory() as holder, stock_factory() as waiter:
            stale = await waiter.get(StockItem, stock_id)
            assert stale.qty_reserved == 7
            waiter_pid = await waiter.scalar(text("SELECT pg_backend_pid()"))
            holder_pid = await holder.scalar(text("SELECT pg_backend_pid()"))
            await service.reserve(holder, [{"sku_code": "SHARED", "qty": 2}])
            await holder.flush()

            async def release():
                result = await service.release(waiter, [{"sku_code": "SHARED", "qty": 3}])
                await waiter.commit()
                return result

            task = asyncio.create_task(release())
            await _assert_blocked(stock_factory, holder_pid, waiter_pid, task)
            await holder.commit()
            assert await asyncio.wait_for(task, 10) == [
                {"sku_code": "SHARED", "qty": 3.0, "warehouse": "Главный"},
            ]
        async with stock_factory() as check:
            assert (await check.scalar(select(StockItem))).qty_reserved == Decimal("6")
    finally:
        if task is not None:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
