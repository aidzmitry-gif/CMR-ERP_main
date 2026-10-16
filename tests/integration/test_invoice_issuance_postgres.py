"""Actual issuance against the frozen proposal in a fresh test-owned PostgreSQL DB."""

import asyncio
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from core.domain.models import Sku
from core.runtime.app import create_app
from core.runtime.deps import get_session
from modules.accounting.models import AccessGrant
from modules.sales.accounting_ownership import DealOwnership
from modules.sales.client_document_register import DealClientBinding, preview_snapshot
from modules.sales.invoice_issuance import InvoiceIssuanceReceipt
from modules.sales.models import Deal, DealDocument, DealItem
from modules.wms.models import ReservationVersion, StockMovement, Task
from tests.accounting.test_postgres import pg_factory  # noqa: F401
from tests.test_invoice_issuance import command, create, erp_money_flow, seed


@pytest_asyncio.fixture
async def issuance_pg(pg_factory):  # noqa: F811
    factory = pg_factory
    async with factory() as session:
        conn = await session.connection()
        tables = {Sku.__table__, DealItem.__table__}
        pending = list(tables)
        while pending:
            for fk in pending.pop().foreign_keys:
                target = fk.column.table
                if target not in tables:
                    tables.add(target)
                    pending.append(target)
        await conn.run_sync(lambda c: Sku.metadata.create_all(c, tables=list(tables), checkfirst=True))
        await session.commit()
    app = create_app()
    app.state.core.services.db.session_factory = factory

    async def request_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = request_session
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-User": "issuer", "X-User-Roles": "director"},
    ) as client:
        yield client, factory


async def test_pg_long_author_issue_reserve_delivery_and_truncate_guard(issuance_pg):
    from core.services.eventbus import OutboxEventBus
    from modules.accounting.gateway import AccountingService
    from modules.sales.reservation_source import SalesReservationSource
    from modules.wms.events import on_stock_reserved

    client, factory = issuance_pg
    async with factory() as session:
        ids, base = await seed(client, session, suffix=uuid4().hex[:8])
        actor = "issuer-" + "x" * 193
        session.add(AccessGrant(organization_id=ids["org"], subject=actor, role="chief"))
        await session.commit()
    client.headers["X-User"] = actor
    cmd, _ = await command(client, ids, base, key=uuid4().hex)
    issued = await create(client, ids, cmd)
    assert issued.status_code == 201, issued.text
    doc_id = issued.json()["document"]["id"]
    async with factory() as session:
        assert (await session.get(DealDocument, doc_id)).issued_by == actor
        assert (await session.get(InvoiceIssuanceReceipt, doc_id)).actor == actor
        for sql in ("TRUNCATE sales.invoice_issuance_receipt", "DELETE FROM sales.invoice_issuance_receipt"):
            with pytest.raises(DBAPIError, match="immutable"):
                await session.execute(text(sql))
            await session.rollback()
        assert await session.get(InvoiceIssuanceReceipt, doc_id) is not None
    bus = OutboxEventBus()
    bus.subscribe("sales.stock.reserved", on_stock_reserved)
    services = create_app().state.core.services
    services.accounting = AccountingService()
    services.sales_source = SalesReservationSource()
    assert await bus.relay_pending(factory, services, event_types=("sales.stock.reserved",)) == 1
    assert await bus.relay_pending(factory, services, event_types=("sales.stock.reserved",)) == 0
    replay = await create(client, ids, cmd)
    assert replay.status_code == 200 and replay.json()["replayed"]
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(Task)) == 1
        assert await session.scalar(select(func.count()).select_from(ReservationVersion)) == 1
        assert await session.scalar(select(func.count()).select_from(StockMovement)) == 1


async def test_pg_erp_invoice_bank_receipt_refund_and_reconciliation(issuance_pg):
    client, factory = issuance_pg
    async with factory() as session:
        await erp_money_flow(client, session)


async def test_pg_stored_reservation_rejects_nan_at_database_boundary(issuance_pg):
    from decimal import Decimal

    _, factory = issuance_pg
    async with factory() as session:
        session.add(ReservationVersion(organization_id=1, source="invalid-nan", version=1,
            sku_code="A", warehouse="W", qty=Decimal("NaN"), evidence="Synthetic invalid", actor="tester"))
        with pytest.raises(DBAPIError, match="wms_reservation_valid"):
            await session.flush()
        await session.rollback()
        assert await session.scalar(select(func.count()).select_from(ReservationVersion)) == 0


async def test_pg_concurrent_same_key_produces_one_receipt_and_sql_immutability(issuance_pg):
    client, factory = issuance_pg
    async with factory() as session:
        ids, base = await seed(client, session, suffix=uuid4().hex[:8])
    cmd, _ = await command(client, ids, base, key=uuid4().hex)
    first, second = await asyncio.gather(create(client, ids, cmd), create(client, ids, cmd))
    assert sorted([first.status_code, second.status_code]) == [200, 201], (first.text, second.text)
    doc_id = first.json()["document"]["id"]
    assert second.json()["document"]["id"] == doc_id
    async with factory() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(InvoiceIssuanceReceipt)
                .where(InvoiceIssuanceReceipt.document_id == doc_id)
            )
            == 1
        )
        with pytest.raises(DBAPIError, match="immutable"):
            await session.execute(
                text("UPDATE sales.invoice_issuance_receipt SET actor=actor WHERE document_id=:id"),
                {"id": doc_id},
            )
        await session.rollback()


async def test_pg_parallel_invoices_cannot_overissue_same_org_stock(issuance_pg):
    client, factory = issuance_pg
    async with factory() as session:
        ids, base = await seed(client, session, physical="3", suffix=uuid4().hex[:8])
        other = Deal(
            number=uuid4().hex, title="Competing invoice", counterparty="Ignored", amount=0
        )
        session.add(other)
        await session.flush()
        line = DealItem(deal_id=other.id, sku_id=ids["sku"], qty=2)
        session.add(line)
        session.add(
            DealOwnership(
                deal_id=other.id,
                organization_id=ids["org"],
                snapshot={},
                evidence="Synthetic",
                actor="issuer",
            )
        )
        await session.flush()
        session.add(
            DealClientBinding(
                deal_id=other.id,
                organization_id=ids["org"],
                counterparty_id=ids["buyer"],
                snapshot=await preview_snapshot(session, ids["org"], other, ids["buyer"]),
                evidence="Synthetic",
                actor="issuer",
            )
        )
        await session.commit()
        second_ids = {**ids, "deal": other.id, "item": line.id}
    first_cmd, _ = await command(client, ids, base, key=uuid4().hex)
    other_base = {
        **base,
        "pricing": [
            {"item_id": second_ids["item"], "unit_price_net": "100.00", "vat_rate": "20.00"}
        ],
    }
    second_cmd, _ = await command(client, second_ids, other_base, key=uuid4().hex)
    results = await asyncio.gather(
        create(client, ids, first_cmd), create(client, second_ids, second_cmd)
    )
    assert sorted(r.status_code for r in results) == [201, 409], [r.text for r in results]
    async with factory() as session:
        assert (
            await session.scalar(
                select(func.sum(ReservationVersion.qty)).where(
                    ReservationVersion.organization_id == ids["org"]
                )
            )
            == 2
        )

@pytest.mark.parametrize("mixed_legacy", [False, True])
async def test_pg_concurrent_expiry_ticks_emit_one_reminder(issuance_pg, monkeypatch, mixed_legacy):
    from datetime import date, datetime, time, timezone

    from core.domain.models import OutboxEvent
    from modules.sales.reserve import tick_invoice_reserve

    client, factory = issuance_pg
    legacy_deal_id = None
    async with factory() as setup:
        ids, base = await seed(client, setup, suffix=uuid4().hex[:8])
        if mixed_legacy:
            legacy = Deal(number=uuid4().hex, title="Synthetic legacy", counterparty="Synthetic")
            setup.add(legacy)
            await setup.flush()
            legacy_deal_id = legacy.id
            setup.add(DealOwnership(deal_id=legacy.id, organization_id=ids["org"],
                snapshot={}, evidence="Synthetic mixed sweep", actor="issuer"))
            setup.add(DealDocument(deal_id=legacy.id, kind="invoice", number="LEGACY",
                status="draft", reserve_status="reserved", valid_until=date(2099, 1, 1)))
            await setup.commit()
    cmd, _ = await command(client, ids, base, key=uuid4().hex)
    issued = await create(client, ids, cmd)
    assert issued.status_code == 201, issued.text
    doc_id = issued.json()["document"]["id"]
    async with factory() as read:
        doc = await read.get(DealDocument, doc_id)
        moment = datetime.combine(doc.valid_until, time(12), timezone.utc)
    monkeypatch.setattr("modules.sales.reserve._utcnow", lambda: moment)
    services = client._transport.app.state.core.services
    ready, release, started = asyncio.Event(), asyncio.Event(), asyncio.Event()
    pids = {}

    async def first():
        async with factory() as session:
            pids["first"] = await session.scalar(text("select pg_backend_pid()"))
            if mixed_legacy:
                await services.accounting.lock_event_organization(session, ids["org"])
            else:
                await tick_invoice_reserve(session, services)
            await session.flush()
            ready.set()
            await asyncio.wait_for(release.wait(), 15)
            if mixed_legacy:
                from modules.sales.documents import lock_deal
                await lock_deal(session, legacy_deal_id)
            await session.commit()

    async def second():
        async with factory() as session:
            pids["second"] = await session.scalar(text("select pg_backend_pid()"))
            started.set()
            await tick_invoice_reserve(session, services)
            await session.commit()

    first_task = asyncio.create_task(first())
    second_task = None
    try:
        await asyncio.wait_for(ready.wait(), 15)
        second_task = asyncio.create_task(second())
        await asyncio.wait_for(started.wait(), 15)
        async with factory() as observer:
            for _ in range(100):
                blockers = await observer.scalar(text("select pg_blocking_pids(:pid)"), {"pid": pids["second"]})
                if pids["first"] in blockers:
                    break
                await asyncio.sleep(.02)
            else:
                pytest.fail("Second expiry tick did not wait on the first PostgreSQL transaction")
        assert pids["first"] != pids["second"]
    finally:
        release.set()
        await asyncio.wait_for(asyncio.gather(first_task, *([second_task] if second_task else [])), 20)
    async with factory() as check:
        assert await check.scalar(select(func.count()).select_from(OutboxEvent).where(
            OutboxEvent.event_type == "sales.invoice.expiring")) == 1
        doc = await check.get(DealDocument, doc_id)
        assert doc.status == "issued" and doc.reserve_status == "reserved" and doc.reminded_at is not None
