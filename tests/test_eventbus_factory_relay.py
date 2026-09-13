"""Factory delivery owns one transaction per event; ambient relay stays unchanged."""
import asyncio
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.db.base import Base
from core.domain.models import AuditLog, OutboxEvent
from core.services.eventbus import OutboxEventBus


@pytest_asyncio.fixture
async def factory(tmp_path):
    engine = create_async_engine("sqlite+aiosqlite:///" + (tmp_path / "relay.db").as_posix())
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(
            c, tables=[OutboxEvent.__table__, AuditLog.__table__]))
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def seed(factory, events):
    async with factory() as session:
        session.add_all([OutboxEvent(event_type=kind, payload=data) for kind, data in events])
        await session.commit()


@pytest.mark.parametrize("failure", ["handler", "cancel", "commit"])
async def test_event_boundary_preserves_previous_success_and_suppresses_failed_callbacks(factory, monkeypatch, failure):
    await seed(factory, [("first", {}), ("second", {})])
    bus = OutboxEventBus()
    notifications = []

    async def good(payload, ctx):
        ctx.after_commit(lambda: notifications.append("first"))
        bus.emit(ctx.session, "derived", {})

    async def bad(payload, ctx):
        ctx.session.add(AuditLog(action="partial", detail={}))
        ctx.after_commit(lambda: notifications.append("second"))
        await ctx.session.flush()
        if failure == "handler":
            raise ValueError("synthetic failure")
        if failure == "cancel":
            raise asyncio.CancelledError()

    bus.subscribe("first", good)
    bus.subscribe("second", bad)
    original_commit = AsyncSession.commit
    commits = 0

    async def commit(session):
        nonlocal commits
        commits += 1
        if commits == 2:
            raise RuntimeError("synthetic commit failure")
        await original_commit(session)

    if failure == "commit":
        monkeypatch.setattr(AsyncSession, "commit", commit)
    expected = {"handler": ValueError, "cancel": asyncio.CancelledError, "commit": RuntimeError}[failure]
    with pytest.raises(expected):
        await bus.relay_pending(factory, SimpleNamespace())
    assert notifications == ["first"]
    async with factory() as session:
        events = (await session.scalars(select(OutboxEvent).order_by(OutboxEvent.id))).all()
        assert [row.event_type for row in events] == ["first", "second", "derived"]
        assert [row.processed_at is not None for row in events] == [True, False, False]
        assert (await session.scalars(select(AuditLog.action))).all() == ["first"]


async def test_new_worker_never_flushes_ambient_session_and_defers_derived_events(factory):
    await seed(factory, [("first", {})])
    bus = OutboxEventBus()
    sessions = []

    async def handler(payload, ctx):
        sessions.append(ctx.session)
        bus.emit(ctx.session, "derived", {})

    bus.subscribe("first", handler)
    async with factory() as ambient:
        pending = AuditLog(action="caller-uncommitted", detail={})
        ambient.add(pending)
        assert await bus.relay_pending(factory, SimpleNamespace()) == 1
        assert pending in ambient.new and ambient not in sessions
        async with factory() as check:
            assert await check.scalar(select(func.count()).select_from(AuditLog)) == 1
            assert await check.scalar(select(func.count()).select_from(OutboxEvent).where(
                OutboxEvent.processed_at.is_(None))) == 1
        await ambient.rollback()
    assert await bus.relay_pending(factory, SimpleNamespace()) == 1


async def test_factory_phone_failure_does_not_overtake_same_call(factory):
    incoming, ended = "telephony.call.incoming", "telephony.call.ended"
    await seed(factory, [(incoming, {"call_id": "A"}), (ended, {"call_id": "A"}),
                         (incoming, {"call_id": "B"}), (ended, {"call_id": "B"})])
    bus = OutboxEventBus()
    delivered = []
    poison = True

    async def start(payload, ctx):
        if poison and payload["call_id"] == "A":
            raise ValueError("synthetic poison")
        ctx.after_commit(lambda: delivered.append(("start", payload["call_id"])))

    async def end(payload, ctx):
        ctx.after_commit(lambda: delivered.append(("end", payload["call_id"])))

    bus.subscribe(incoming, start)
    bus.subscribe(ended, end)
    assert await bus.relay_pending(factory, SimpleNamespace()) == 2
    assert delivered == [("start", "B"), ("end", "B")]
    poison = False
    assert await bus.relay_pending(factory, SimpleNamespace()) == 2
    assert delivered[-2:] == [("start", "A"), ("end", "A")]


async def test_poison_page_does_not_starve_independent_events(factory):
    incoming = "telephony.call.incoming"
    await seed(factory, [(incoming, {"call_id": "A"}), (incoming, {"call_id": "B"}), ("healthy", {})])
    bus = OutboxEventBus()

    async def poison(payload):
        raise ValueError("synthetic poison")

    bus.subscribe(incoming, poison)
    assert await bus.relay_pending(factory, SimpleNamespace(), limit=2) == 0
    assert await bus.relay_pending(factory, SimpleNamespace(), limit=2) == 1
    # Wrapping revisits the pending poison, preserving retryability.
    assert await bus.relay_pending(factory, SimpleNamespace(), limit=2) == 0
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(OutboxEvent).where(
            OutboxEvent.processed_at.is_not(None))) == 1


async def test_failure_after_wrap_retries_failed_event_before_new_arrivals(factory):
    incoming = "telephony.call.incoming"
    await seed(factory, [(incoming, {"call_id": "A"}), ("healthy", {})])
    bus = OutboxEventBus()

    async def poison(payload):
        raise ValueError("synthetic isolated failure")

    bus.subscribe(incoming, poison)
    assert await bus.relay_pending(factory, SimpleNamespace()) == 1

    # A later non-isolated failure on the old pending row must stop delivery,
    # including when the scheduler had already advanced beyond that row.
    fail = True
    observed = []

    async def guarded_relay(session, ctx=None, **kwargs):
        event_id = kwargs["_only_event_id"]
        if fail and event_id == 1:
            raise RuntimeError("synthetic worker failure")
        observed.append(event_id)
        return await original(session, ctx, **kwargs)

    original = bus.relay_once
    bus.relay_once = guarded_relay
    with pytest.raises(RuntimeError, match="worker failure"):
        await bus.relay_pending(factory, SimpleNamespace())
    await seed(factory, [("new-arrival", {})])
    with pytest.raises(RuntimeError, match="worker failure"):
        await bus.relay_pending(factory, SimpleNamespace())
    assert observed == []
    fail = False
    assert await bus.relay_pending(factory, SimpleNamespace()) == 1
    assert observed == [1, 3]
