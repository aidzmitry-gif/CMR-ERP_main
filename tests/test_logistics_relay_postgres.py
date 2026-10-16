"""Actual relay + actual Logistics/WMS handlers; wrappers only pause or inject faults."""
import asyncio
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select, text, update

from core.db.base import Base
from core.domain.models import AuditLog, OutboxEvent
from core.runtime.app import create_app
from core.services.auth import CurrentUser
from modules.accounting.models import AccessGrant, Organization
from modules.accounting.service import lock_organization
from modules.logistics import events as logistics_events
from modules.logistics import shipment_writer
from modules.logistics.models import (
    Shipment,
    ShipmentIntake,
    ShipmentInvoiceBinding,
    ShipmentJournal,
)
from modules.sales.accounting_ownership import DealOwnership
from modules.sales.models import Deal, DealDocument
from modules.wms.events import on_stock_reserved
from modules.wms.invoice_reservations import ReserveInput, reserve
from modules.wms.models import ReservationVersion, StockMovement, Task
from modules.wms.reservation_events import ReservationEventState, ReservationPick
from tests.accounting.test_postgres import pg_factory  # noqa: F401

TIMEOUT = 15


async def ready(event):
    await asyncio.wait_for(event.wait(), TIMEOUT)


async def blocked_by(factory, waiter, holder):
    """Polling only detects an actual PG wait; elapsed time is never evidence."""
    async with asyncio.timeout(TIMEOUT):
        async with factory() as observer:
            while True:
                blockers = await observer.scalar(text("SELECT pg_blocking_pids(:pid)"), {"pid": waiter})
                if holder in blockers:
                    row = (await observer.execute(text(
                        "SELECT wait_event_type,wait_event FROM pg_stat_activity WHERE pid=:pid"),
                        {"pid": waiter})).one()
                    assert row.wait_event_type == "Lock"
                    return {"waiter": waiter, "holder": holder, "wait_event": row.wait_event}
                await asyncio.sleep(0.02)


def evidence(name, data):
    path = Path(os.environ["SHIPMENT_PG_EVIDENCE_DIR"]) / (name + ".json")
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


@pytest_asyncio.fixture
async def pg(pg_factory, tmp_path, monkeypatch):  # noqa: F811
    """Use the common fresh database and frozen accounting schema proposal."""
    factory = pg_factory
    monkeypatch.setenv("SHIPMENT_PG_EVIDENCE_DIR", str(tmp_path))
    core = create_app().state.core
    wanted = {m.__table__ for m in (Task, ReservationEventState, ReservationPick)}
    todo = list(wanted)
    while todo:
        for fk in todo.pop().foreign_keys:
            dep = fk.column.table
            if dep not in wanted:
                wanted.add(dep)
                todo.append(dep)
    async with factory() as session:
        conn = await session.connection()
        await conn.run_sync(lambda sync: Base.metadata.create_all(sync, tables=list(wanted), checkfirst=True))
        await session.commit()
    actor = CurrentUser(username="pg-shipment", roles=["logistics"])
    html = "<p>synthetic PG invoice</p>"
    exact = dict(organization_id=1, document_id=1, expected_version=1,
                 expected_content_sha256=hashlib.sha256(html.encode()).hexdigest())
    async with factory() as session:
        session.add(Organization(id=1, name="Synthetic", unp="999999981"))
        session.add(Deal(id=1, number="PG-D1", title="Synthetic", counterparty="Synthetic"))
        await session.flush()
        session.add(AccessGrant(organization_id=1, subject=actor.username, role="chief"))
        session.add(DealOwnership(deal_id=1, organization_id=1, snapshot={}, evidence="Synthetic", actor=actor.username))
        session.add(DealDocument(id=1, deal_id=1, number="PG-I1", kind="invoice", status="paid",
            reserve_status="reserved", version=1, amount=100, original_html=html,
            content_sha256=exact["expected_content_sha256"], issued_at=datetime(2026, 9, 10),
            snapshot_json={"items": [{"sku_code": "A", "qty": "2"}]}))
        session.add(StockMovement(organization_id=1, sku_code="A", warehouse="W", kind="in", qty=10, reason="receipt"))
        session.add(ShipmentJournal(id=1, generation=0))
        await session.flush()
        await lock_organization(session, 1)
        source = await core.services.sales_source.invoice_reservation(session, 1)
        await reserve(session, 1, source, ReserveInput(allocations=[{"line_no": 1, "warehouse": "W", "qty": "2"}],
            journal_complete=True, evidence="Synthetic physical journal"), actor.username)
        await session.commit()
    yield SimpleNamespace(factory=factory, core=core, exact=exact, actor=actor)


async def queue_pair(pg, kind):
    bus = pg.core.services.event_bus
    # Select only the actual handlers under test, without unrelated finance projections.
    bus._handlers.clear()
    event_type = "sales.document.posted" if kind == "order" else "logistics.delivery.requested"
    stock = dict(document_id=1, organization_id=1, items=[{"sku_code": "A", "warehouse": "W", "qty": "2"}])
    async with pg.factory() as s:
        one = OutboxEvent(event_type=event_type, version=1, payload={"kind": "order", "source_key": f"{kind}:1", "source_revision": "1"})
        two = OutboxEvent(event_type="stock.reserved", version=1, payload=stock)
        s.add(one)
        await s.flush()
        s.add(two)
        await s.commit()
        return event_type, stock, (one.id, two.id)


async def assert_effects(pg, ids):
    async with pg.factory() as s:
        intake = (await s.scalars(select(ShipmentIntake))).one()
        assert intake.state == "pending" and intake.pending_reason == "persisted_source_required"
        for i in ids:
            assert (await s.get(OutboxEvent, i)).processed_at is not None
        state = await s.get(ReservationEventState, 1)
        assert state.state == "reserved" and state.quantities == {"A": "2.00"}
        picks = list(await s.scalars(select(ReservationPick)))
        tasks = list(await s.scalars(select(Task)))
        assert len(picks) == len(tasks) == 1
        assert tasks[0].kind == "pick" and tasks[0].status == "open" and tasks[0].qty == 2
        assert len(list(await s.scalars(select(ReservationVersion)))) == 1
        movements = list(await s.scalars(select(StockMovement)))
        assert len(movements) == 1 and movements[0].kind == "in"


@pytest.mark.parametrize("kind", ["order", "office"])
async def test_real_batch_journal_org_interleave(pg, kind):
    event_type, stock, ids = await queue_pair(pg, kind)
    bus = pg.core.services.event_bus
    actual = logistics_events.on_document_posted if kind == "order" else logistics_events.on_office_delivery_requested
    intake_ready, release_intake, writer_started = asyncio.Event(), asyncio.Event(), asyncio.Event()
    writer_created, release_writer, stock_started = asyncio.Event(), asyncio.Event(), asyncio.Event()
    trace, tasks = {}, []

    async def intake(payload, ctx):
        await actual(payload, ctx)
        trace["intake_pid"] = await ctx.session.scalar(text("SELECT pg_backend_pid()"))
        trace["intake_txid"] = await ctx.session.scalar(text("SELECT txid_current()"))
        intake_ready.set()
        await ready(release_intake)

    async def reserved(payload, ctx):
        pid = await ctx.session.scalar(text("SELECT pg_backend_pid()"))
        txid = await ctx.session.scalar(text("SELECT txid_current()"))
        trace.setdefault("stock_pid", pid)
        trace.setdefault("stock_txid", txid)
        trace.setdefault("stock_deliveries", []).append({"pid": pid, "txid": txid})
        stock_started.set()
        await on_stock_reserved(payload, ctx)

    async def writer():
        async with pg.factory() as session:
            trace["writer_pid"] = await session.scalar(text("SELECT pg_backend_pid()"))
            writer_started.set()
            result = await shipment_writer.create(session, pg.core, pg.exact, "parallel:1", {"customer": "Synthetic", "status": "planned"}, pg.actor)
            trace["shipment_id"] = result.id
            writer_created.set()
            await ready(release_writer)
            await session.commit()

    bus.subscribe(event_type, intake)
    bus.subscribe("stock.reserved", reserved)
    try:
        relay = asyncio.create_task(bus.relay_pending(pg.factory, pg.core.services, event_types=[event_type, "stock.reserved"]))
        tasks.append(relay)
        await ready(intake_ready)
        task = asyncio.create_task(writer())
        tasks.append(task)
        await ready(writer_started)
        trace["journal_wait"] = await blocked_by(pg.factory, trace["writer_pid"], trace["intake_pid"])
        release_intake.set()
        await ready(writer_created)
        await ready(stock_started)
        trace["org_wait"] = await blocked_by(pg.factory, trace["stock_pid"], trace["writer_pid"])
        assert trace["org_wait"]["waiter"] == trace["stock_deliveries"][0]["pid"]
        async with pg.factory() as observer:
            assert (await observer.get(OutboxEvent, ids[0])).processed_at is not None
            assert (await observer.get(OutboxEvent, ids[1])).processed_at is None
            assert (await observer.scalars(select(ShipmentIntake))).one().state == "pending"
        assert trace["intake_txid"] != trace["stock_txid"]
        release_writer.set()
        assert await asyncio.wait_for(relay, TIMEOUT) == 2
        await asyncio.wait_for(task, TIMEOUT)
        await assert_effects(pg, ids)
        # A second real stock event still creates no second pick or reservation.
        async with pg.factory() as s:
            bus.emit(s, "stock.reserved", stock)
            await s.commit()
        assert await bus.relay_pending(pg.factory, pg.core.services, event_types=[event_type, "stock.reserved"]) == 1
        await assert_effects(pg, ids)
        evidence("interleave-" + kind, trace)
    finally:
        release_intake.set()
        release_writer.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.parametrize("kind", ["order", "office"])
async def test_second_event_rollback_preserves_first_and_retries_actual_handler(pg, kind):
    event_type, _, ids = await queue_pair(pg, kind)
    bus = pg.core.services.event_bus
    actual = logistics_events.on_document_posted if kind == "order" else logistics_events.on_office_delivery_requested
    fail = True

    async def reserved(payload, ctx):
        await on_stock_reserved(payload, ctx)
        await ctx.session.flush()
        if fail:
            raise RuntimeError("synthetic failure after real WMS handler")

    bus.subscribe(event_type, actual)
    bus.subscribe("stock.reserved", reserved)
    with pytest.raises(RuntimeError, match="synthetic failure"):
        await bus.relay_pending(pg.factory, pg.core.services, event_types=[event_type, "stock.reserved"])
    async with pg.factory() as s:
        assert (await s.get(OutboxEvent, ids[0])).processed_at is not None
        assert (await s.get(OutboxEvent, ids[1])).processed_at is None
        assert (await s.scalars(select(ShipmentIntake))).one().state == "pending"
        assert list(await s.scalars(select(Task))) == []
        assert list(await s.scalars(select(ReservationPick))) == []
        assert await s.get(ReservationEventState, 1) is None
        assert list(await s.scalars(select(AuditLog).where(AuditLog.action == "stock.reserved"))) == []
    fail = False
    assert await bus.relay_pending(pg.factory, pg.core.services, event_types=[event_type, "stock.reserved"]) == 1
    await assert_effects(pg, ids)
    assert await bus.relay_pending(pg.factory, pg.core.services, event_types=[event_type, "stock.reserved"]) == 0


async def test_same_key_concurrent_replay_and_conflict(pg):
    committed = asyncio.Event()
    release = asyncio.Event()
    started = asyncio.Event()
    trace, tasks = {}, []

    async def first():
        async with pg.factory() as s:
            trace["first_pid"] = await s.scalar(text("SELECT pg_backend_pid()"))
            row = await shipment_writer.create(s, pg.core, pg.exact, "same", {"customer": "Synthetic"}, pg.actor)
            trace["first_id"] = row.id
            committed.set()
            await ready(release)
            await s.commit()

    async def second():
        async with pg.factory() as s:
            trace["second_pid"] = await s.scalar(text("SELECT pg_backend_pid()"))
            started.set()
            row = await shipment_writer.create(s, pg.core, pg.exact, "same", {"customer": "Synthetic"}, pg.actor)
            trace["second_id"] = row.id
            await s.commit()
    try:
        tasks.append(asyncio.create_task(first()))
        await ready(committed)
        tasks.append(asyncio.create_task(second()))
        await ready(started)
        await blocked_by(pg.factory, trace["second_pid"], trace["first_pid"])
        release.set()
        await asyncio.wait_for(asyncio.gather(*tasks), TIMEOUT)
        assert trace["first_id"] == trace["second_id"]
        async with pg.factory() as s:
            with pytest.raises(HTTPException) as caught:
                await shipment_writer.create(s, pg.core, pg.exact, "same", {"customer": "Changed"}, pg.actor)
            assert caught.value.status_code == 409
            await s.rollback()
            assert len(list(await s.scalars(select(Shipment)))) == 1
            assert len(list(await s.scalars(select(ShipmentInvoiceBinding)))) == 1
    finally:
        release.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def test_source_terminal_race_uses_actual_writer_and_source(pg):
    """Synthetic terminal transition; not acceptance of the cancellation-act workflow."""
    trace = {}
    started = asyncio.Event()
    task = None

    async def writer():
        async with pg.factory() as s:
            trace["writer_pid"] = await s.scalar(text("SELECT pg_backend_pid()"))
            started.set()
            with pytest.raises(HTTPException) as caught:
                await shipment_writer.create(s, pg.core, pg.exact, "terminal", {"customer": "Synthetic"}, pg.actor)
            assert caught.value.status_code == 409
            await s.rollback()
    try:
        async with pg.factory() as terminal:
            await lock_organization(terminal, 1)
            await pg.core.services.sales_source.invoice_shipping_source(terminal, **pg.exact)
            trace["holder_pid"] = await terminal.scalar(text("SELECT pg_backend_pid()"))
            await terminal.execute(update(DealDocument).where(DealDocument.id == 1).values(reserve_status="released"))
            task = asyncio.create_task(writer())
            await ready(started)
            await blocked_by(pg.factory, trace["writer_pid"], trace["holder_pid"])
            await terminal.commit()
        await asyncio.wait_for(task, TIMEOUT)
        async with pg.factory() as s:
            assert list(await s.scalars(select(Shipment))) == []
            assert list(await s.scalars(select(ShipmentInvoiceBinding))) == []
    finally:
        if task is not None:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
