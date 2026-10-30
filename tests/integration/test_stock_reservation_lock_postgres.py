"""Real stock contention: dedicated G02 service checks and current migrated ERP issue."""
import asyncio
import os
from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import Request
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.schema import CreateSchema, DropSchema

from core.db.base import Base
from core.domain.models import OutboxEvent, Sku
from core.runtime.deps import get_session
from modules.integrations.models import StockItem
from modules.integrations.stock import StockService
from modules.sales.models import Deal, DealDocument, DealItem
from tests.accounting.test_postgres import pg_factory  # noqa: F401
from tests.integration.joint_postgres import is_joint_test_url
from tests.integration.test_invoice_issuance_postgres import issuance_pg  # noqa: F401


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


@pytest.mark.parametrize("wms_enabled", [False, True])
async def test_cancelled_replacement_and_new_invoice_serialize_stock_reservations(
    issuance_pg, monkeypatch, wms_enabled,  # noqa: F811 -- imported pytest fixture
):
    """A reconciled HIGH cancellation precedes concurrent LOW / LOW+HIGH issues."""
    from modules.sales.accounting_ownership import DealOwnership
    from modules.sales.client_document_register import DealClientBinding, preview_snapshot
    from modules.sales.invoice_cancellation import InvoiceCancellationReceipt
    from modules.sales.invoice_issuance import verified_receipt
    from modules.wms.invoice_reservations import InvoiceReservationRelease
    from modules.wms.models import ReservationVersion, StockMovement, WarehouseDirectory
    from tests.integration.test_document_original_postgres import _cancel_for_replacement
    from tests.test_invoice_issuance import command, create, seed

    api, factory = issuance_pg
    app = api._transport.app
    assert not getattr(app.state.core.services.onec, "outbound_document_source_available", False)
    async with factory() as session:
        low = Sku(code="LOW", title="Replacement goods", unit="шт")
        session.add(low)
        await session.commit()
        low_id = low.id
        ids, base = await seed(api, session, suffix="-HIGH", wms_enabled=wms_enabled)
        competitor = Deal(number="COMPETE", title="LOW + HIGH", counterparty="Exact buyer-HIGH")
        session.add(competitor)
        await session.flush()
        session.add(DealOwnership(deal_id=competitor.id, organization_id=ids["org"],
            snapshot={}, evidence="Synthetic competing invoice ownership", actor="issuer"))
        session.add(DealClientBinding(deal_id=competitor.id, organization_id=ids["org"],
            counterparty_id=ids["buyer"], snapshot=await preview_snapshot(
                session, ids["org"], competitor, ids["buyer"]),
            evidence="Synthetic competing invoice buyer", actor="issuer"))
        items = [DealItem(deal_id=competitor.id, sku_id=sku, qty=2) for sku in (low_id, ids["sku"])]
        session.add_all(items)
        session.add(StockMovement(organization_id=ids["org"], sku_code="LOW", warehouse="W",
            kind="in", qty=10, reason="receipt"))
        await session.commit()
        other_ids = {**ids, "deal": competitor.id}
        other_base = {**base, "pricing": [{"item_id": item.id, "unit_price_net": "100.00",
                                          "vat_rate": "20.00"} for item in items]}

    initial, _ = await command(api, ids, base)
    issued = await create(api, ids, initial)
    assert issued.status_code == 201, issued.text
    invoice = issued.json()["document"]
    old_id = invoice["id"]
    old_original = (await api.get(f"/sales/documents/{old_id}/render")).content
    await _cancel_for_replacement(api, ids, invoice)
    async with factory() as session:
        assert await session.scalar(select(InvoiceCancellationReceipt.document_id)) == old_id
        assert await session.scalar(select(InvoiceReservationRelease.document_id)) == old_id
    revision = await api.post(f"/sales/documents/{old_id}/revision", json={
        "reason": "Use LOW instead of HIGH", "request_key": "current-stock-replacement",
    })
    assert revision.status_code == 201, revision.text
    replacement_id = revision.json()["id"]
    async with factory() as session:
        item = await session.get(DealItem, ids["item"])
        item.sku_id, item.qty = low_id, Decimal("3")
        await session.commit()
    revised, _ = await command(api, ids, base, doc_id=replacement_id, key="issue-replacement")
    other, _ = await command(api, other_ids, other_base, key="issue-competitor")

    backend_pids = {}
    request_started, reserved, proceed = asyncio.Event(), asyncio.Event(), asyncio.Event()
    replacement_path = f"/sales/documents/{replacement_id}/issue"
    watch_path = f"/sales/deals/{other_ids['deal']}/documents"
    original_dependency = app.dependency_overrides[get_session]

    async def own_session(request: Request):
        async with factory() as session:
            backend_pids[request.url.path] = await session.scalar(text("SELECT pg_backend_pid()"))
            if request.url.path == watch_path:
                request_started.set()
            yield session

    gateway = app.state.core.services.wms_reservations
    original_reserve = gateway.reserve_invoice

    async def pause_after_reserve(session, organization_id, source, request, actor):
        result = await original_reserve(session, organization_id, source, request, actor)
        if source["document_id"] == replacement_id:
            await session.flush()
            reserved.set()
            await asyncio.wait_for(proceed.wait(), 15)
        return result

    tasks = []
    app.dependency_overrides[get_session] = own_session
    monkeypatch.setattr(gateway, "reserve_invoice", pause_after_reserve)
    try:
        replacement = asyncio.create_task(api.post(replacement_path, json=revised))
        tasks.append(replacement)
        await asyncio.wait_for(reserved.wait(), 15)
        competing = asyncio.create_task(api.post(watch_path, json={"kind": "invoice", **other}))
        tasks.append(competing)
        await asyncio.wait_for(request_started.wait(), 15)
        await _assert_blocked(factory, backend_pids[replacement_path], backend_pids[watch_path], competing)
        assert not competing.done()
        proceed.set()
        responses = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), 20)
        outcomes = [getattr(getattr(result, "orig", None), "sqlstate", None)
                    if isinstance(result, Exception) else result.status_code for result in responses]
        assert outcomes == [200, 201], responses
        other_id = responses[1].json()["document"]["id"]
    finally:
        proceed.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        app.dependency_overrides[get_session] = original_dependency

    async with factory() as check:
        latest = {}
        for row in await check.scalars(select(ReservationVersion).where(
            ReservationVersion.organization_id == ids["org"]).order_by(ReservationVersion.id)):
            latest[row.source] = row
        totals = {code: sum(row.qty for row in latest.values() if row.sku_code == code)
                  for code in ("LOW", ids["code"])}
        assert totals == {"LOW": Decimal("5"), ids["code"]: Decimal("2")}
        assert all(row.qty >= 0 and row.qty <= 10 for row in latest.values())
        movements = list(await check.scalars(select(StockMovement).where(
            StockMovement.organization_id == ids["org"])))
        assert len(movements) == 2 and all(row.kind == "in" and row.qty == 10 for row in movements)
        old = await check.get(DealDocument, old_id)
        assert old.original_html.encode() == old_original and old.reserve_status == "released"
        assert old.status == "cancelled" and old.content_sha256 == invoice["content_sha256"]
        assert old.superseded_by_id == replacement_id
        for doc_id in (replacement_id, other_id):
            doc = await check.get(DealDocument, doc_id)
            assert doc.status == "issued" and doc.reserve_status == "reserved"
            assert await verified_receipt(check, doc, ids["org"]) is not None
        issued_events = list(await check.scalars(select(OutboxEvent).where(
            OutboxEvent.event_type == "sales.invoice.issued")))
        assert len(issued_events) == 3
        warehouse = await check.scalar(select(WarehouseDirectory).where(
            WarehouseDirectory.organization_id == ids["org"], WarehouseDirectory.name == "W"))
        assert warehouse.wms_enabled is wms_enabled and warehouse.prohibit_negative_stock is True
    assert (await api.get(f"/sales/documents/{old_id}/render")).content == old_original


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
