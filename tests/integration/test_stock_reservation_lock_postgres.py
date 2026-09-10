"""Actual row-lock contention in disposable metadata on the dedicated G02 database."""
import asyncio
import os
from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.schema import CreateSchema, DropSchema

from modules.integrations.models import StockItem
from modules.integrations.stock import StockService


@pytest_asyncio.fixture
async def stock_factory():
    raw_url = os.environ.get("CRM_READY_G02_DATABASE_URL")
    if not raw_url:
        pytest.skip("Set CRM_READY_G02_DATABASE_URL to the isolated G02 PostgreSQL")
    url = make_url(raw_url)
    if (url.host, url.port, url.database) != ("127.0.0.1", 15439, "crm_ready_g02"):
        pytest.fail("G02 tests require their dedicated loopback database on port 15439")
    schema = f"g02_stock_{uuid4().hex}"
    engine = create_async_engine(url).execution_options(
        schema_translate_map={"integrations": schema},
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
