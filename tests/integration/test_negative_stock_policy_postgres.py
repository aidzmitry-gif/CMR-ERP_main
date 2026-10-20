import asyncio
import os
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.db.base import Base
from core.runtime.app import create_app
from core.runtime.deps import get_session
from core.services.auth import CurrentUser
from modules.accounting.gateway import AccountingService
from modules.sales.reservation_source import SalesReservationSource
from modules.wms.invoice_shipments import create
from modules.wms.models import StockMovement
from modules.wms.warehouse_catalog import WarehouseStockPolicyUpdate, update_stock_policy
from tests.test_warehouse_execution_mode import prepared


@pytest_asyncio.fixture
async def pg_book_api():
    target = os.environ.get("NEGATIVE_STOCK_TEST_PG_URL")
    if not target:
        pytest.skip("Set owned local NEGATIVE_STOCK_TEST_PG_URL for PostgreSQL checks")
    url = make_url(target)
    assert url.host == "127.0.0.1" and url.database == "postgres" and url.port
    engine = create_async_engine(url)
    async with engine.begin() as connection:
        for schema in sorted({t.schema for t in Base.metadata.tables.values() if t.schema}):
            assert schema.replace("_", "").isalnum()
            await connection.execute(text('CREATE SCHEMA IF NOT EXISTS "' + schema + '"'))
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    app = create_app()
    app.state.core.services.db.session_factory = factory

    async def sessions():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = sessions
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-User": "allocator", "X-User-Roles": "director"},
    ) as api:
        yield factory, api, app.state.core
    async with engine.begin() as connection:
        for schema in sorted({t.schema for t in Base.metadata.tables.values() if t.schema}):
            await connection.execute(text('DROP SCHEMA "' + schema + '" CASCADE'))
        await connection.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.mark.parametrize("wms", [False, True])
async def test_two_competing_shipments_do_not_overdraw(pg_book_api, wms):
    factory, api, core = pg_book_api
    async with factory() as s:
        org, facts, actor, warehouse, basis, command = await prepared(api, s, wms)
        s.add(
            StockMovement(
                organization_id=org,
                sku_code="A",
                warehouse="W",
                kind="out",
                qty=9,
                reason="shipment",
            )
        )
        await s.flush()
        from modules.wms.invoice_shipments import preview

        b = await preview(s, org, facts)
        command = command.model_copy(update={"expected_physical_digest": b["physical_digest"]})
        await s.commit()
    held = asyncio.Event()
    release = asyncio.Event()
    started = asyncio.Event()

    async def writer(key, first):
        if not first:
            await held.wait()
        async with factory() as s:
            try:
                if not first:
                    await s.execute(text("SET LOCAL application_name='negative_policy_ship2'"))
                    started.set()
                who = await AccountingService().source_member(
                    s, org, CurrentUser("allocator", ["director"])
                )
                if first:
                    held.set()
                    await release.wait()
                current = await SalesReservationSource().invoice_shipping_source(
                    s,
                    facts["document_id"],
                    organization_id=org,
                    expected_version=facts["version"],
                    expected_content_sha256=facts["content_sha256"],
                )
                _result = await create(
                    s,
                    org,
                    current,
                    command.model_copy(update={"source_key": key}),
                    who,
                    execution_mode="wms" if wms else "document",
                )
                await s.commit()
                return 201
            except HTTPException as e:
                await s.rollback()
                return e.status_code

    tasks = [
        asyncio.create_task(writer(uuid4(), True)),
        asyncio.create_task(writer(uuid4(), False)),
    ]
    try:
        await asyncio.wait_for(started.wait(), 10)
        async with factory() as observer:
            for attempt in range(50):
                blocked = await observer.scalar(
                    text(
                        "SELECT count(*) FROM pg_stat_activity WHERE application_name='negative_policy_ship2' AND wait_event_type='Lock'"
                    )
                )
                if blocked == 1:
                    break
                await asyncio.sleep(0.1)
            else:
                raise AssertionError("second shipment never blocked on first organization lock")
        release.set()
        results = await asyncio.wait_for(asyncio.gather(*tasks), 20)
        assert sorted(results) == [201, 409], results
    finally:
        release.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    async with factory() as s:
        from modules.wms.invoice_reservations import invoice_availability

        await s.execute(text("SELECT 1"))
        state = await invoice_availability(s, org, ["A"])
        assert next(r for r in state["rows"] if r["warehouse"] == "W")["physical"] == "0.00"


async def test_policy_switch_serializes_with_outbound_guard(pg_book_api):
    factory, api, core = pg_book_api
    async with factory() as s:
        org, facts, actor, warehouse, basis, command = await prepared(api, s, False)
        warehouse.prohibit_negative_stock = False
        wid = warehouse.id
        s.add(
            StockMovement(
                organization_id=org,
                sku_code="A",
                warehouse="W",
                kind="out",
                qty=10,
                reason="shipment",
            )
        )
        await s.commit()
    held = asyncio.Event()
    release = asyncio.Event()
    started = asyncio.Event()

    async def setter():
        async with factory() as s:
            await AccountingService().source_member(s, org, CurrentUser("allocator", ["director"]))
            await update_stock_policy(
                org,
                wid,
                WarehouseStockPolicyUpdate(
                    expected_prohibit_negative_stock=False, prohibit_negative_stock=True
                ),
                session=s,
                core=core,
                user=CurrentUser("allocator", ["director"]),
            )
            held.set()
            await release.wait()
            await s.commit()

    async def writer():
        await held.wait()
        async with factory() as s:
            await s.execute(text("SET LOCAL application_name='negative_policy_setting2'"))
            started.set()
            await AccountingService().source_member(s, org, CurrentUser("allocator", ["director"]))
            from modules.wms.invoice_shipments import preview

            current = await SalesReservationSource().invoice_shipping_source(
                s,
                facts["document_id"],
                organization_id=org,
                expected_version=facts["version"],
                expected_content_sha256=facts["content_sha256"],
            )
            b = await preview(s, org, current)
            try:
                await create(
                    s,
                    org,
                    current,
                    command.model_copy(update={"expected_physical_digest": b["physical_digest"]}),
                    actor,
                    execution_mode="document",
                )
            except HTTPException as e:
                assert e.detail["code"] == "stock_shortage"
                await s.rollback()
                return 409
            raise AssertionError("stale policy allowed negative stock")

    setting = asyncio.create_task(setter())
    writing = asyncio.create_task(writer())
    try:
        await asyncio.wait_for(started.wait(), 10)
        async with factory() as observer:
            for attempt in range(50):
                blocked = await observer.scalar(
                    text(
                        "SELECT count(*) FROM pg_stat_activity WHERE application_name='negative_policy_setting2' AND wait_event_type='Lock'"
                    )
                )
                if blocked == 1:
                    break
                await asyncio.sleep(0.1)
            else:
                raise AssertionError("outbound never blocked on policy setter")
        assert not writing.done()
        release.set()
        await asyncio.wait_for(setting, 10)
        assert await asyncio.wait_for(writing, 10) == 409
    finally:
        release.set()
        for task in (setting, writing):
            if not task.done():
                task.cancel()
        await asyncio.gather(setting, writing, return_exceptions=True)


async def test_additive_policy_migration_default_and_downgrade_guard(pg_book_api):
    import importlib.util

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy.exc import DBAPIError

    factory, api, core = pg_book_api
    async with factory() as session:
        org, _, _, warehouse, _, _ = await prepared(api, session, False)
        wid = warehouse.id
        await session.commit()
    path = __import__("pathlib").Path("migrations/versions/0194_warehouse_negative_stock_policy.py")
    spec = importlib.util.spec_from_file_location("policy_migration_118", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    async with factory() as session:
        await session.execute(
            text("ALTER TABLE wms.warehouse_directory DROP COLUMN prohibit_negative_stock")
        )
        connection = await session.connection()

        def upgrade(conn):
            module.op = Operations(MigrationContext.configure(conn))
            module.upgrade()

        await connection.run_sync(upgrade)
        assert (
            await session.scalar(
                text("SELECT prohibit_negative_stock FROM wms.warehouse_directory WHERE id=:id"),
                {"id": wid},
            )
            is True
        )
        await session.execute(
            text("UPDATE wms.warehouse_directory SET prohibit_negative_stock=false WHERE id=:id"),
            {"id": wid},
        )
        await session.commit()
    async with factory() as session:
        connection = await session.connection()

        def downgrade(conn):
            module.op = Operations(MigrationContext.configure(conn))
            module.downgrade()

        with pytest.raises(DBAPIError) as caught:
            await connection.run_sync(downgrade)
        assert "Disable negative-stock exceptions before removing the policy" in str(caught.value)
        await session.rollback()
        assert (
            await session.scalar(
                text("SELECT prohibit_negative_stock FROM wms.warehouse_directory WHERE id=:id"),
                {"id": wid},
            )
            is False
        )
