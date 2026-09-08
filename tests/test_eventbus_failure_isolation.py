"""Phone savepoints isolate malformed projections without relaxing financial ordering."""
import asyncio
import os
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.db.base import Base
from core.domain.models import AuditLog, OutboxEvent
from core.services.eventbus import EventContext, OutboxEventBus
from modules.sales import calls
from modules.sales.models import CallLog, Deal

INCOMING = "telephony.call.incoming"
ANSWERED = "telephony.call.answered"
ENDED = "telephony.call.ended"
OWNER = "SYNTHETIC-OWNER"


@pytest_asyncio.fixture(params=["sqlite", "postgresql"])
async def relay_factory(request):
    """Only generated schemas in an explicitly selected synthetic loopback PG DB."""
    schema = None
    if request.param == "postgresql":
        raw_url = os.environ.get("CRM_TELEPHONY_TEST_DATABASE_URL", "")
        if not raw_url:
            pytest.skip("Set CRM_TELEPHONY_TEST_DATABASE_URL for the PostgreSQL oracle")
        url = make_url(raw_url)
        if (
            url.get_backend_name() != "postgresql"
            or url.host not in {"127.0.0.1", "localhost", "::1"}
            or not (url.database or "").startswith("crm_tel_test")
            or url.query
        ):
            pytest.skip("Requires loopback, no URL options, and a crm_tel_test database")
        schema = "telephony_relay_test_" + uuid4().hex
    else:
        url = "sqlite+aiosqlite:///:memory:"
    engine = create_async_engine(url).execution_options(schema_translate_map={None: schema, "sales": schema})
    tables = [Deal.__table__, CallLog.__table__, OutboxEvent.__table__, AuditLog.__table__]
    created = False
    try:
        async with engine.begin() as connection:
            if schema is not None:
                await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
                created = True
            await connection.run_sync(lambda conn: Base.metadata.create_all(conn, tables=tables))
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        if created:
            async with engine.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await engine.dispose()


def _ctx(session, bus):
    return EventContext(session=session, services=SimpleNamespace(event_bus=bus))


async def _seed(factory, events, *, owned_calls=()):
    async with factory() as session:
        session.add_all([
            CallLog(call_id=key, direction="in", owner=OWNER, status="ringing")
            for key in owned_calls
        ])
        session.add_all([OutboxEvent(event_type=kind, payload=payload) for kind, payload in events])
        await session.commit()


async def test_sql_error_rolls_back_only_phone_unit_and_retries_in_order(relay_factory):
    bus = OutboxEventBus()
    poison = True
    notifications = []
    attempts = []

    async def incoming(payload, ctx):
        key = payload["call_id"]
        attempts.append(key)
        ctx.session.add(AuditLog(action="partial.phone", entity_ref=key, detail=payload))
        await ctx.session.flush()
        ctx.after_commit(lambda: notifications.append(key))
        if key == "A" and poison:
            # Failure is deferred to the relay's final flush, after processed_at
            # and the normal success audit have also been staged.
            ctx.session.add(AuditLog(action=None, detail={}))

    finished = []
    bus.subscribe(INCOMING, incoming)
    bus.subscribe(ENDED, lambda payload: finished.append(payload["call_id"]))
    bus.subscribe("safe.independent", lambda payload: finished.append("safe"))
    original = {"call_id": "A", "agent_ext": "synthetic-invalid"}
    await _seed(relay_factory, [
        (INCOMING, original), (ENDED, {"call_id": "A"}),
        (INCOMING, {"call_id": "B"}), ("safe.independent", {}),
    ])

    async with relay_factory() as session:
        assert await bus.relay_once(session, _ctx(session, bus)) == 2
        assert notifications == ["B"]
        assert finished == ["safe"]
        events = (await session.scalars(select(OutboxEvent).order_by(OutboxEvent.id))).all()
        assert [event.processed_at is not None for event in events] == [False, False, True, True]
        assert events[0].payload == original
        assert await session.scalar(select(func.count()).select_from(AuditLog).where(
            AuditLog.entity_ref == "A",
        )) == 0
        assert await bus.relay_once(session, _ctx(session, bus)) == 0
        assert attempts == ["A", "B", "A"]
        assert notifications == ["B"]
        poison = False
        assert await bus.relay_once(session, _ctx(session, bus)) == 2
        assert finished == ["safe", "A"]
        assert notifications == ["B", "A"]
        assert await bus.relay_once(session, _ctx(session, bus)) == 0
        assert await session.scalar(select(func.count()).select_from(AuditLog).where(
            AuditLog.action == INCOMING,
        )) == 2


async def test_filtered_relay_sees_earlier_call_and_matches_python_strip(relay_factory):
    bus = OutboxEventBus()
    delivered = []
    bus.subscribe(INCOMING, lambda payload: delivered.append("incoming"))
    bus.subscribe(ENDED, lambda payload: delivered.append(payload["call_id"]))
    await _seed(relay_factory, [
        (INCOMING, {"call_id": "\t A\u00a0"}),
        (ENDED, {"call_id": "A"}), (ENDED, {"call_id": "B"}),
    ])
    async with relay_factory() as session:
        assert await bus.relay_once(session, _ctx(session, bus), event_types=(ENDED,)) == 1
        assert delivered == ["B"]
        assert await bus.relay_once(session, _ctx(session, bus), event_types=(INCOMING,)) == 1
        assert await bus.relay_once(session, _ctx(session, bus), event_types=(ENDED,)) == 1
        assert delivered == ["B", "incoming", "A"]


async def test_sse_publishes_distinct_snapshots_only_after_commit(relay_factory, monkeypatch):
    bus = OutboxEventBus()
    for kind, handler in calls.EVENT_HANDLERS.items():
        bus.subscribe(kind, handler)
    await _seed(relay_factory, [
        (INCOMING, {"call_id": "A"}), (ANSWERED, {"call_id": "A"}), (ENDED, {"call_id": "A"}),
    ], owned_calls=("A",))
    queue = calls.subscribe(OWNER)
    try:
        async with relay_factory() as session:
            real_commit = session.commit

            async def checked_commit():
                assert queue.empty()
                await real_commit()

            monkeypatch.setattr(session, "commit", checked_commit)
            assert await bus.relay_once(session, _ctx(session, bus)) == 3
            assert [queue.get_nowait()["status"] for _ in range(3)] == ["ringing", "answered", "ended"]
            assert queue.empty()
            # Derived sales.call.ended is delivered on the next pass, with no new SSE.
            assert await bus.relay_once(session, _ctx(session, bus)) == 1
            assert queue.empty()
    finally:
        calls.unsubscribe(OWNER, queue)


async def test_failed_phone_discards_sse_and_derived_events(relay_factory):
    bus = OutboxEventBus()
    bus.subscribe(ENDED, calls.on_call_ended)

    async def poison(payload, ctx):
        raise ValueError("synthetic bad event")

    bus.subscribe(ENDED, poison)
    bus.subscribe(ANSWERED, calls.on_call_answered)
    await _seed(relay_factory, [
        (ENDED, {"call_id": "A"}), (ANSWERED, {"call_id": "B"}),
    ], owned_calls=("A", "B"))
    queue = calls.subscribe(OWNER)
    try:
        async with relay_factory() as session:
            assert await bus.relay_once(session, _ctx(session, bus)) == 1
            card = queue.get_nowait()
            assert (card["call_id"], card["status"]) == ("B", "answered")
            assert queue.empty()
            states = dict((await session.execute(select(CallLog.call_id, CallLog.status))).all())
            assert states == {"A": "ringing", "B": "answered"}
            assert await session.scalar(select(func.count()).select_from(OutboxEvent).where(
                OutboxEvent.event_type == "sales.call.ended",
            )) == 0
            assert await bus.relay_once(session, _ctx(session, bus)) == 0
            assert queue.empty()
    finally:
        calls.unsubscribe(OWNER, queue)


@pytest.mark.parametrize("failure", ["finance", "commit", "cancel"])
async def test_outer_failure_rolls_back_phone_and_suppresses_sse(relay_factory, monkeypatch, failure):
    bus = OutboxEventBus()
    bus.subscribe(ANSWERED, calls.on_call_answered)
    later_calls = []

    async def fail(payload):
        if failure == "cancel":
            raise asyncio.CancelledError
        raise RuntimeError("synthetic outer failure")

    failure_type = INCOMING if failure == "cancel" else "finance.payment.accrued"
    bus.subscribe(failure_type, fail)
    bus.subscribe("finance.payment.paid", lambda payload: later_calls.append("paid"))
    events = [(ANSWERED, {"call_id": "A"})]
    if failure != "commit":
        events.extend([(failure_type, {"call_id": "B"}), ("finance.payment.paid", {})])
    await _seed(relay_factory, events, owned_calls=("A",))
    queue = calls.subscribe(OWNER)
    try:
        async with relay_factory() as session:
            if failure == "commit":
                async def failed_commit():
                    raise RuntimeError("synthetic outer failure")

                monkeypatch.setattr(session, "commit", failed_commit)
            expected = asyncio.CancelledError if failure == "cancel" else RuntimeError
            with pytest.raises(expected):
                await bus.relay_once(session, _ctx(session, bus))
            await session.rollback()
            assert queue.empty()
            assert later_calls == []
        async with relay_factory() as check:
            assert await check.scalar(select(CallLog.status)) == "ringing"
            assert await check.scalar(select(func.count()).select_from(AuditLog)) == 0
            assert await check.scalar(select(func.count()).select_from(OutboxEvent).where(
                OutboxEvent.processed_at.is_not(None),
            )) == 0
    finally:
        calls.unsubscribe(OWNER, queue)


async def test_preexisting_dirty_flush_error_propagates(relay_factory, caplog):
    bus = OutboxEventBus()
    delivered = []
    bus.subscribe(INCOMING, lambda payload: delivered.append(payload))
    await _seed(relay_factory, [(INCOMING, {"call_id": "A"})])
    async with relay_factory() as session:
        session.autoflush = False
        session.add(AuditLog(action=None, detail={}))
        with pytest.raises(IntegrityError):
            await bus.relay_once(session, _ctx(session, bus))
        await session.rollback()
        assert delivered == []
        assert "isolated telephony relay error" not in caplog.text
        assert await session.scalar(select(OutboxEvent.processed_at)) is None


async def test_existing_caller_transaction_survives_isolated_phone_failure(relay_factory):
    bus = OutboxEventBus()

    async def poison(payload):
        raise ValueError("synthetic phone failure")

    bus.subscribe(INCOMING, poison)
    await _seed(relay_factory, [(INCOMING, {"call_id": "A"})])
    async with relay_factory() as session:
        session.add(AuditLog(action="caller.pending", detail={}))
        await session.flush()  # Real transaction already active before relay.
        assert await bus.relay_once(session, _ctx(session, bus)) == 0
    async with relay_factory() as check:
        assert (await check.scalars(select(AuditLog.action))).all() == ["caller.pending"]
        assert await check.scalar(select(OutboxEvent.processed_at)) is None


async def test_prior_finance_dirty_flush_error_is_not_isolated_as_phone(relay_factory, caplog):
    bus = OutboxEventBus()
    delivered = []

    async def finance(payload, ctx):
        ctx.session.add(AuditLog(action=None, detail={}))

    bus.subscribe("finance.payment.accrued", finance)
    bus.subscribe(INCOMING, lambda payload: delivered.append("phone"))
    await _seed(relay_factory, [("finance.payment.accrued", {}), (INCOMING, {"call_id": "A"})])
    async with relay_factory() as session:
        with pytest.raises(IntegrityError):
            await bus.relay_once(session, _ctx(session, bus))
        await session.rollback()
        assert delivered == []
        assert "isolated telephony relay error" not in caplog.text
        assert await session.scalar(select(func.count()).select_from(AuditLog)) == 0


@pytest.mark.parametrize("stage", ["start", "connection", "release", "rollback"])
async def test_savepoint_infrastructure_errors_propagate(relay_factory, monkeypatch, stage):
    bus = OutboxEventBus()
    notifications = []

    async def incoming(payload, ctx):
        ctx.after_commit(lambda: notifications.append("card"))
        if stage == "rollback":
            raise ValueError("synthetic handler failure")

    bus.subscribe(INCOMING, incoming)
    await _seed(relay_factory, [(INCOMING, {"call_id": "A"})])
    async with relay_factory() as session:
        async def failed_operation():
            raise RuntimeError(f"synthetic {stage} failure")

        if stage in {"start", "connection"}:
            monkeypatch.setattr(session, "begin_nested" if stage == "start" else "connection", failed_operation)
        else:
            real_begin = session.begin_nested

            async def begin_with_fault():
                transaction = await real_begin()
                return SimpleNamespace(
                    commit=failed_operation if stage == "release" else transaction.commit,
                    rollback=failed_operation if stage == "rollback" else transaction.rollback,
                )

            monkeypatch.setattr(session, "begin_nested", begin_with_fault)
        with pytest.raises(RuntimeError, match=f"synthetic {stage} failure"):
            await bus.relay_once(session, _ctx(session, bus))
        await session.rollback()
        assert notifications == []


async def test_unknown_telephony_type_is_still_fail_stop(relay_factory):
    bus = OutboxEventBus()

    async def poison(payload):
        raise ValueError("unknown handler failure")

    delivered = []
    bus.subscribe("telephony.call.future", poison)
    bus.subscribe("safe.independent", lambda payload: delivered.append("safe"))
    await _seed(relay_factory, [("telephony.call.future", {}), ("safe.independent", {})])
    async with relay_factory() as session:
        with pytest.raises(ValueError, match="unknown handler failure"):
            await bus.relay_once(session, _ctx(session, bus))
        await session.rollback()
        assert delivered == []


async def test_notification_failure_after_commit_does_not_lose_later_cards(relay_factory, caplog):
    bus = OutboxEventBus()
    delivered = []

    def broken_card():
        raise RuntimeError("synthetic notification failure")

    async def incoming(payload, ctx):
        ctx.after_commit(broken_card)
        ctx.after_commit(lambda: delivered.append("card"))

    bus.subscribe(INCOMING, incoming)
    await _seed(relay_factory, [(INCOMING, {"call_id": "A"})])
    async with relay_factory() as session:
        assert await bus.relay_once(session, _ctx(session, bus)) == 1
        assert delivered == ["card"]
        assert await session.scalar(select(OutboxEvent.processed_at)) is not None
        assert "post-commit relay notification error" in caplog.text


async def test_missing_required_context_fails_closed_then_retries_once(relay_factory):
    bus = OutboxEventBus()
    delivered = []
    bus.subscribe(INCOMING, lambda payload: delivered.append(payload["call_id"]))
    bus.subscribe(INCOMING, calls.on_incoming_call)
    await _seed(relay_factory, [(INCOMING, {"call_id": "A"})])
    async with relay_factory() as session:
        with pytest.raises(ValueError, match="EventContext is required for telephony.call.incoming delivery"):
            await bus.relay_once(session)
        await session.rollback()
        assert delivered == []  # Preflight prevents even earlier handlers running.
        assert await session.scalar(select(OutboxEvent.processed_at)) is None
        assert await session.scalar(select(func.count()).select_from(CallLog)) == 0
        assert await session.scalar(select(func.count()).select_from(AuditLog)) == 0

        assert await bus.relay_once(session, _ctx(session, bus), event_types=(INCOMING,)) == 1
        assert await bus.relay_once(session, _ctx(session, bus), event_types=(INCOMING,)) == 0
        assert delivered == ["A"]
        assert await session.scalar(select(func.count()).select_from(CallLog)) == 1
        assert await session.scalar(select(func.count()).select_from(AuditLog).where(
            AuditLog.action == INCOMING,
        )) == 1
        assert await session.scalar(select(OutboxEvent.processed_at).where(
            OutboxEvent.event_type == INCOMING,
        )) is not None


async def test_context_free_phone_handler_still_delivers_without_context(relay_factory):
    bus = OutboxEventBus()
    delivered = []
    bus.subscribe(INCOMING, lambda payload: delivered.append(payload["call_id"]))
    await _seed(relay_factory, [(INCOMING, {"call_id": "A"})])
    async with relay_factory() as session:
        assert await bus.relay_once(session) == 1
        assert await bus.relay_once(session) == 0
        assert delivered == ["A"]
        assert await session.scalar(select(OutboxEvent.processed_at)) is not None
        assert (await session.scalars(select(AuditLog.action))).all() == [INCOMING]


@pytest.mark.integration
async def test_postgres_locked_predecessor_blocks_same_call_only(relay_factory):
    async with relay_factory() as probe:
        if probe.get_bind().dialect.name != "postgresql":
            pytest.skip("Concurrent SKIP LOCKED semantics require PostgreSQL")
    bus1, bus2 = OutboxEventBus(), OutboxEventBus()
    started, release = asyncio.Event(), asyncio.Event()
    delivered = []

    async def held_incoming(payload):
        started.set()
        await release.wait()
        raise ValueError("synthetic held predecessor failure")

    bus1.subscribe(INCOMING, held_incoming)
    bus2.subscribe(ENDED, lambda payload: delivered.append(payload["call_id"]))
    bus2.subscribe("safe.independent", lambda payload: delivered.append("safe"))
    await _seed(relay_factory, [
        (INCOMING, {"call_id": "\tA "}), (ENDED, {"call_id": "A"}),
        (ENDED, {"call_id": "B"}), ("safe.independent", {}),
    ])

    async def consume_predecessor():
        async with relay_factory() as session:
            return await bus1.relay_once(session, _ctx(session, bus1), event_types=(INCOMING,))

    task = asyncio.create_task(consume_predecessor())
    try:
        await asyncio.wait_for(started.wait(), timeout=5)
        async with relay_factory() as session:
            # The general SELECT skips A's locked predecessor. The ordinary
            # identity snapshot still sees it, without waiting on its row lock.
            assert await asyncio.wait_for(bus2.relay_once(session, _ctx(session, bus2)), timeout=5) == 2
            assert delivered == ["B", "safe"]
            assert not release.is_set()
        release.set()
        assert await asyncio.wait_for(asyncio.shield(task), timeout=5) == 0
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async with relay_factory() as check:
        events = (await check.scalars(select(OutboxEvent).order_by(OutboxEvent.id))).all()
        assert [event.processed_at is not None for event in events] == [False, False, True, True]
    bus1._handlers[INCOMING].clear()
    async with relay_factory() as session:
        assert await bus1.relay_once(session, _ctx(session, bus1), event_types=(INCOMING,)) == 1
    async with relay_factory() as session:
        assert await bus2.relay_once(session, _ctx(session, bus2), event_types=(ENDED,)) == 1
        assert delivered == ["B", "safe", "A"]
        assert await bus2.relay_once(session, _ctx(session, bus2)) == 0
