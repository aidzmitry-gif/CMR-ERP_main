"""Landed source identity and transactional delivery in test-owned PostgreSQL 16."""
import asyncio
from copy import deepcopy
from datetime import datetime
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from core.domain.models import AuditLog, OutboxEvent
from core.runtime.app import create_app
from core.runtime.deps import get_session
from core.services.eventbus import EventContext
from modules.finance.events import on_landed_cost
from modules.finance.models import Payment, PaymentAllocation
from modules.procurement import order_edit_commands as commands
from modules.procurement.models import (
    PurchaseOrder,
)
from modules.procurement.ownership import PurchaseOwnership
from tests.accounting.test_postgres import pg_factory as pg_factory  # noqa: F401
from tests.accounting.test_procurement_order_edit_commands import command
from tests.test_finance import received_landed, seeded_landed_order

EVENT = "procurement.landed_cost.calculated"
pytestmark = [pytest.mark.integration,
              pytest.mark.parametrize("pg_factory", ["registered_head"], indirect=True)]


@pytest_asyncio.fixture
async def landed_pg(pg_factory):
    factory = pg_factory
    app = create_app()
    app.state.core.services.db.session_factory = factory
    async def request_session():
        async with factory() as session:
            yield session
    app.dependency_overrides[get_session] = request_session
    core = app.state.core
    assert core.event_bus._handlers[EVENT] == [on_landed_cost]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test",
        headers={"X-User": "issuer", "X-User-Roles": "director"}) as api:
        yield api, factory, core


async def seeded_order(runtime, suffix):
    return await seeded_landed_order(runtime, suffix)


async def received(runtime, action="status", suffix="1"):
    item = await received_landed(runtime, action, suffix)
    assert Decimal(item["payload"]["total_landed_byn"]) == Decimal("1.01")
    assert Decimal(item["payload"]["unit_landed_cost_byn"]) * Decimal("2") == Decimal("1.0200")
    return item


async def receipt_snapshot(factory):
    async with factory() as session:
        return (await session.execute(select(commands.PurchaseOrderEditCommand.__table__)
            .order_by(commands.PurchaseOrderEditCommand.id))).all()


async def dispatch_same(runtime, item):
    _, factory, core = runtime
    async with factory() as session:
        await core.event_bus.dispatch(EVENT, deepcopy(item["payload"]),
            EventContext(session, core.services, event_id=item["event"]))
        await session.commit()


async def projection_snapshot(runtime, items, delivered):
    _, factory, _ = runtime
    async with factory() as session:
        rows = (await session.scalars(select(Payment).order_by(Payment.id))).all()
        assert len(rows) == len(items)
        by_owner = {row.organization_id: row for row in rows}
        for item in items:
            row = by_owner[item["org"]]
            assert row.ref == f"landed:purchase_order:{item['order']}:LANDED-SAME"
            assert row.entity_ref.startswith(f"landed-receipt:{item['receipt']}:{item['order']}:")
            assert row.amount == Decimal("1.01") and row.currency == "BYN"
            assert row.status == "recorded" and row.paid_at is None
            assert row.account_id is row.deal_id is row.counterparty_ref is None
            assert (await session.get(OutboxEvent, item["event"])).processed_at is not None
        assert await session.scalar(select(func.count()).select_from(PaymentAllocation)) == 0
        assert await session.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == EVENT)) == delivered
        return [(row.id, row.organization_id, row.entity_ref, row.description, row.amount, row.status) for row in rows]


async def test_pg_landed_original_event_concurrent_replay(landed_pg, monkeypatch):
    _, factory, core = landed_pg
    item = await received(landed_pg)
    frozen = await receipt_snapshot(factory)
    bus, services = core.event_bus, core.services
    acquired, replay_entered, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    real_lock = services.accounting.lock_event_organization
    pids, workers = {}, []

    async def gated_lock(session, org):
        pid = await session.scalar(text("SELECT pg_backend_pid()"))
        if not pids:
            pids["relay"] = pid
            await real_lock(session, org)
            acquired.set()
            await asyncio.wait_for(release.wait(), timeout=10)
        else:
            pids["replay"] = pid
            replay_entered.set()
            await real_lock(session, org)

    async def relay():
        async with factory() as session:
            return await bus.relay_once(session, EventContext(session, services),
                event_types=(EVENT,), _only_event_id=item["event"])

    with monkeypatch.context() as patch:
        patch.setattr(services.accounting, "lock_event_organization", gated_lock)
        try:
            workers.append(asyncio.create_task(relay()))
            await asyncio.wait_for(acquired.wait(), timeout=10)
            workers.append(asyncio.create_task(dispatch_same(landed_pg, item)))
            await asyncio.wait_for(replay_entered.wait(), timeout=10)
            assert pids["relay"] != pids["replay"]
            async with factory() as observer:
                for _ in range(125):
                    blockers = await observer.scalar(text("SELECT pg_blocking_pids(:pid)"), {"pid": pids["replay"]})
                    if pids["relay"] in blockers:
                        break
                    await asyncio.sleep(0.02)
                else:
                    raise AssertionError("Replay did not block on the original organization transaction")
                assert await observer.scalar(select(func.count()).select_from(Payment)) == 0
                assert (await observer.get(OutboxEvent, item["event"])).processed_at is None
            release.set()
            assert await asyncio.wait_for(asyncio.gather(*workers), timeout=20) == [1, None]
        finally:
            release.set()
            for worker in workers:
                if not worker.done():
                    worker.cancel()
            await asyncio.wait_for(asyncio.gather(*workers, return_exceptions=True), timeout=10)
            assert all(worker.done() for worker in workers)
    before = await projection_snapshot(landed_pg, [item], 1)
    await dispatch_same(landed_pg, item)
    assert await projection_snapshot(landed_pg, [item], 1) == before
    assert await bus.relay_pending(factory, services, event_types=(EVENT,)) == 0
    assert await receipt_snapshot(factory) == frozen


async def test_pg_landed_flush_rollback_retry(landed_pg, monkeypatch):
    _, factory, core = landed_pg
    item = await received(landed_pg, "save")
    frozen = await receipt_snapshot(factory)
    async with factory() as session:
        real_flush = session.flush

        async def fail_after_insert(*args, **kwargs):
            inserting = any(isinstance(row, Payment) for row in session.new)
            await real_flush(*args, **kwargs)
            if inserting:
                raise RuntimeError("Injected native landed flush failure")

        with monkeypatch.context() as patch:
            patch.setattr(session, "flush", fail_after_insert)
            with pytest.raises(RuntimeError, match="Injected native landed flush"):
                await core.event_bus.relay_once(session, EventContext(session, core.services),
                    event_types=(EVENT,), _only_event_id=item["event"])
        await session.rollback()
    async with factory() as fresh:
        assert await fresh.scalar(select(func.count()).select_from(Payment)) == 0
        assert await fresh.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == EVENT)) == 0
        assert (await fresh.get(OutboxEvent, item["event"])).processed_at is None
    assert await receipt_snapshot(factory) == frozen
    assert await core.event_bus.relay_pending(factory, core.services, event_types=(EVENT,)) == 1
    before = await projection_snapshot(landed_pg, [item], 1)
    await dispatch_same(landed_pg, item)
    assert await projection_snapshot(landed_pg, [item], 1) == before
    assert await receipt_snapshot(factory) == frozen


async def historical_receipt(runtime, action, suffix, template):
    """Seed an explicit old-format receipt using real persist and enabled SQL guards."""
    api, factory, core = runtime
    item = await seeded_order(runtime, suffix)
    body = {"status": "received"} if action == "status" else {"status": {"status": "received"}}
    item["cmd"] = command(item["order"], action, body)
    async with factory() as session:
        row = await session.get(PurchaseOrder, item["order"])
        row.status = "received"
        row.received_at = datetime.fromisoformat(template["payload"]["calculation"]["received_at"])
        payload = deepcopy(template["payload"])
        del payload["calculation"]
        payload.update(organization_id=item["org"], purchase_order_id=item["order"])
        core.event_bus.emit(session, EVENT, payload)
        event = next(row for row in session.new if isinstance(row, OutboxEvent))
        await session.flush()
        effect = {"from": "customs", "to": "received", "received_at": row.received_at.isoformat(), "event_ids": [event.id]}
        if action == "save":
            effect = {"status": effect}
        owner = await session.get(PurchaseOwnership, item["owner"])
        result = await commands.persist(session, item["org"], "issuer", commands.EditCommand.model_validate(item["cmd"]),
            owner=owner, effect=effect)
        item.update(event=event.id, payload=deepcopy(payload), result=deepcopy(result))
        await session.commit()
    replay = await api.post(item["endpoint"], json=item["cmd"], headers=item["headers"])
    assert replay.status_code == 200 and replay.json() == item["result"], replay.text
    with pytest.raises(ValueError, match="receipt is unavailable"):
        await dispatch_same(runtime, item)
    async with factory() as session:
        assert (await session.get(OutboxEvent, item["event"])).processed_at is None
    return item


async def test_pg_landed_two_org_sources_and_receipt_guards(landed_pg):
    _, factory, core = landed_pg
    a = await received(landed_pg, "status", "1")
    b = await received(landed_pg, "save", "2")
    assert a["payload"]["shipment_id"] == b["payload"]["shipment_id"]
    assert a["org"] != b["org"] and a["order"] != b["order"]
    assert await core.event_bus.relay_pending(factory, core.services, event_types=(EVENT,)) == 2
    projected = await projection_snapshot(landed_pg, [a, b], 2)
    await historical_receipt(landed_pg, "status", "3", a)
    await historical_receipt(landed_pg, "save", "4", b)
    assert await projection_snapshot(landed_pg, [a, b], 2) == projected
    frozen = await receipt_snapshot(factory)
    assert len(frozen) == 4
    statements = [(f"{verb} procurement.purchase_order_edit_command {tail} WHERE id=:id", {"id": row.id})
                  for row in frozen for verb, tail in (("UPDATE", "SET actor=actor"), ("DELETE FROM", ""))]
    statements.append(("TRUNCATE procurement.purchase_order_edit_command", {}))
    for statement, parameters in statements:
        async with factory() as session:
            with pytest.raises(DBAPIError, match="immutable"):
                await session.execute(text(statement), parameters)
            await session.rollback()
        assert await receipt_snapshot(factory) == frozen
    assert await projection_snapshot(landed_pg, [a, b], 2) == projected
