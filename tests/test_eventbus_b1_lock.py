"""B1 — лок строк outbox против конкурентной двойной доставки (гонка релеев).

``relay_once`` без блокировки строк: синхронный relay в ``convert_lead`` и фоновый
``_background_loop`` (поллинг 2с) могли выбрать ОДНИ и те же строки → двойная
доставка события (двойная сделка/платёж — деньги собственника). Фикс:
``SELECT ... FOR UPDATE SKIP LOCKED``, dialect-aware (только PostgreSQL); на SQLite
(dev/тест — single-writer) деградируем до обычного SELECT.

Настоящую lock-семантику PG на SQLite in-memory не воспроизвести. Регресс-гард
ниже перехватывает РЕАЛЬНЫЙ statement самого ``relay_once`` под замоканным
PostgreSQL-диалектом и проверяет, что он компилируется с FOR UPDATE SKIP LOCKED —
падает без фикса (обычный SELECT), в отличие от простого at-most-once наблюдения.
"""
import asyncio
import os
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.db.base import Base
from core.domain.models import AuditLog, OutboxEvent
from core.services.eventbus import EventContext, OutboxEventBus


class _PGDialect:
    name = "postgresql"


class _PGBind:
    dialect = _PGDialect()


async def test_relay_once_pg_statement_carries_row_lock(session):
    """Регресс-гард B1: под PostgreSQL relay_once строит SELECT ... FOR UPDATE SKIP LOCKED.

    Перехватываем фактический statement, переданный в ``session.execute`` самим
    ``relay_once`` (не ручной), с ``get_bind`` замоканным на postgresql. Без фикса
    (обычный SELECT без лока) assert падает — это и отличает регресс-гард от
    характеризационной проверки at-most-once ниже.
    """
    bus = OutboxEventBus()
    bus.subscribe("b1.money.moved", lambda payload: None)
    bus.emit(session, "b1.money.moved", {"amount": "100.00", "entity_ref": "deal:1"})
    await session.flush()

    real_execute = session.execute
    captured: dict = {}

    async def spy_execute(stmt, *a, **k):
        captured.setdefault("stmt", stmt)  # первый execute в relay_once — SELECT outbox
        return await real_execute(stmt, *a, **k)

    orig_get_bind = session.get_bind
    session.get_bind = lambda *a, **k: _PGBind  # type: ignore[method-assign]
    session.execute = spy_execute  # type: ignore[method-assign]
    try:
        n = await bus.relay_once(session, EventContext(session=session, services=object()))
    finally:
        session.get_bind = orig_get_bind  # type: ignore[method-assign]
        session.execute = real_execute  # type: ignore[method-assign]

    assert n == 1
    compiled = str(captured["stmt"].compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE SKIP LOCKED" in compiled, compiled


async def test_relay_once_no_double_delivery(session):
    """Характеризация: повторный relay_once не доставляет то же событие дважды."""
    calls: list[dict] = []
    bus = OutboxEventBus()
    bus.subscribe("b1.money.moved", lambda payload: calls.append(payload))
    bus.emit(session, "b1.money.moved", {"amount": "100.00", "entity_ref": "deal:1"})
    await session.flush()

    ctx = EventContext(session=session, services=object())
    assert await bus.relay_once(session, ctx) == 1
    assert await bus.relay_once(session, ctx) == 0  # второй релей — брать нечего
    assert len(calls) == 1, "событие не должно доставляться дважды"

    ev = (await session.execute(select(OutboxEvent))).scalars().first()
    assert ev is not None and ev.processed_at is not None


async def test_relay_once_event_type_filter_and_none_path(session):
    """A priority filter processes only matching pending events; None keeps old behavior."""
    calls: list[str] = []
    bus = OutboxEventBus()
    bus.subscribe("priority", lambda payload: calls.append(payload["entity_ref"]))
    bus.subscribe("general", lambda payload: calls.append(payload["entity_ref"]))
    bus.emit(session, "priority", {"entity_ref": "priority:1"})
    bus.emit(session, "general", {"entity_ref": "general:1"})
    await session.flush()

    ctx = EventContext(session=session, services=object())
    assert await bus.relay_once(session, ctx, event_types=("priority",)) == 1
    assert calls == ["priority:1"]
    pending = (await session.execute(select(OutboxEvent).where(
        OutboxEvent.processed_at.is_(None),
    ).order_by(OutboxEvent.id))).scalars().all()
    assert [event.event_type for event in pending] == ["general"]

    assert await bus.relay_once(session, ctx, event_types=()) == 0
    assert calls == ["priority:1"]
    assert await bus.relay_once(session, ctx, event_types=None) == 1
    assert calls == ["priority:1", "general:1"]


async def test_relay_once_empty_filter_does_not_dispatch(session):
    """An empty filter is a SQL empty selection and does not commit or dispatch."""
    calls: list[str] = []
    bus = OutboxEventBus()
    bus.subscribe("priority", lambda payload: calls.append(payload["entity_ref"]))
    bus.emit(session, "priority", {"entity_ref": "priority:empty"})
    await session.flush()

    assert await bus.relay_once(session, EventContext(session=session, services=object()), event_types=()) == 0
    event = (await session.execute(select(OutboxEvent))).scalar_one()
    assert event.processed_at is None
    assert calls == []


async def test_relay_once_default_keeps_fail_stop_order(session):
    """The unfiltered relay stops before a dependent event after a handler error."""
    calls: list[str] = []
    bus = OutboxEventBus()

    async def poison(payload):
        raise ValueError("accrual failed")

    bus.subscribe("finance.payment.accrued", poison)
    bus.subscribe("finance.payment.paid", lambda payload: calls.append("paid"))
    bus.emit(session, "finance.payment.accrued", {"entity_ref": "payment:1"})
    bus.emit(session, "finance.payment.paid", {"entity_ref": "payment:1"})
    await session.flush()
    await session.commit()

    with pytest.raises(ValueError, match="accrual failed"):
        await bus.relay_once(session, EventContext(session=session, services=object()))
    await session.rollback()
    events = (await session.execute(select(OutboxEvent).order_by(OutboxEvent.id))).scalars().all()
    assert [event.processed_at for event in events] == [None, None]
    assert calls == []


async def test_relay_once_propagates_handler_cancellation(session):
    """Cancellation is not converted into a handled delivery failure."""
    bus = OutboxEventBus()

    async def cancel(payload):
        raise asyncio.CancelledError

    bus.subscribe("cancel", cancel)
    bus.emit(session, "cancel", {})
    await session.flush()
    with pytest.raises(asyncio.CancelledError):
        await bus.relay_once(session, EventContext(session=session, services=object()))


@pytest.mark.integration
async def test_relay_once_postgres_filter_and_row_lock():
    """Opt-in PG guard: two consumers contend on the filtered outbox rows."""
    raw_url = os.environ.get("AIOS_DATABASE_URL", "")
    if not raw_url.startswith("postgresql"):
        pytest.skip("Set AIOS_DATABASE_URL to an async PostgreSQL test database")
    url = make_url(raw_url)
    is_ci = os.environ.get("CI", "").lower() in {"1", "true", "yes"}
    safe_local = url.host in {"127.0.0.1", "localhost", "::1"} and (
        url.database or ""
    ).startswith("crm_intake_test")
    if not is_ci and not safe_local:
        pytest.skip("PostgreSQL guard requires CI or an isolated loopback test database")

    schema = "eventbus_test_" + uuid4().hex
    engine = create_async_engine(raw_url).execution_options(
        schema_translate_map={None: schema},
    )
    tables = [OutboxEvent.__table__, AuditLog.__table__]
    created = False
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            created = True
            await connection.run_sync(lambda conn: Base.metadata.create_all(conn, tables=tables))

        factory = async_sessionmaker(engine, expire_on_commit=False)
        bus1 = OutboxEventBus()
        bus2 = OutboxEventBus()
        priority_started = asyncio.Event()
        release_priority = asyncio.Event()
        consumer1_calls: list[str] = []
        consumer2_calls: list[str] = []
        unexpected_priority_calls: list[str] = []

        async def consumer1_priority(payload):
            consumer1_calls.append(payload["entity_ref"])
            priority_started.set()
            await release_priority.wait()

        async def consumer2_priority(payload):
            unexpected_priority_calls.append(payload["entity_ref"])

        bus1.subscribe("priority", consumer1_priority)
        bus2.subscribe("priority", consumer2_priority)
        bus2.subscribe("general", lambda payload: consumer2_calls.append(payload["entity_ref"]))

        async with factory() as seed:
            bus1.emit(seed, "priority", {"entity_ref": "priority:pg"})
            bus1.emit(seed, "general", {"entity_ref": "general:pg"})
            await seed.commit()

        captured: list[object] = []
        consumer1_task = None
        consumer2_task = None

        async def consume_priority():
            async with factory() as session:
                real_execute = session.execute

                async def spy_execute(stmt, *args, **kwargs):
                    captured.append(stmt)
                    return await real_execute(stmt, *args, **kwargs)

                session.execute = spy_execute  # type: ignore[method-assign]
                return await bus1.relay_once(
                    session,
                    EventContext(session=session, services=object()),
                    event_types=("priority",),
                )

        async def consume_general():
            async with factory() as session:
                return await bus2.relay_once(
                    session,
                    EventContext(session=session, services=object()),
                )

        try:
            consumer1_task = asyncio.create_task(consume_priority())
            await asyncio.wait_for(priority_started.wait(), timeout=5)
            consumer2_task = asyncio.create_task(consume_general())
            assert await asyncio.wait_for(asyncio.shield(consumer2_task), timeout=5) == 1
            assert not release_priority.is_set()
            assert consumer1_calls == ["priority:pg"]
            assert consumer2_calls == ["general:pg"]
            assert unexpected_priority_calls == []

            release_priority.set()
            assert await asyncio.wait_for(asyncio.shield(consumer1_task), timeout=5) == 1
        finally:
            release_priority.set()
            for task in (consumer2_task, consumer1_task):
                if task is not None:
                    if not task.done():
                        task.cancel()
                    await asyncio.gather(task, return_exceptions=True)

        assert consumer1_calls == ["priority:pg"]
        assert consumer2_calls == ["general:pg"]
        assert unexpected_priority_calls == []
        compiled = str(captured[0].compile(dialect=postgresql.dialect()))
        assert "event_type IN" in compiled
        assert "FOR UPDATE SKIP LOCKED" in compiled

        async with factory() as check:
            events = (await check.execute(select(OutboxEvent).order_by(OutboxEvent.id))).scalars().all()
            actions = (await check.execute(select(AuditLog.action).order_by(AuditLog.id))).scalars().all()
            assert all(event.processed_at is not None for event in events)
            assert actions.count("priority") == actions.count("general") == 1

        async with factory() as repeat_priority:
            assert await bus1.relay_once(
                repeat_priority,
                EventContext(session=repeat_priority, services=object()),
                event_types=("priority",),
            ) == 0
        async with factory() as repeat_general:
            assert await bus2.relay_once(
                repeat_general,
                EventContext(session=repeat_general, services=object()),
            ) == 0
    finally:
        if created:
            async with engine.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()
