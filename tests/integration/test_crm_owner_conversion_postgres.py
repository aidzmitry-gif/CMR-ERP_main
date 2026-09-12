"""Observe real PostgreSQL locks around lead conversion and owner eligibility."""
from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import func, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.schema import CreateSchema, DropSchema

from core.db.base import Base
from core.domain.models import AuditLog, OutboxEvent, User
from core.services.eventbus import EventContext, OutboxEventBus
from modules.leads.events import on_deal_created_from_lead
from modules.leads.models import Lead, LeadItem
from modules.leads.routes import convert_lead
from modules.sales.events import on_lead_converted
from modules.sales.models import Deal


@pytest_asyncio.fixture
async def owner_factory():
    raw = os.environ.get("CRM_READY_OWNERS_DATABASE_URL")
    if not raw:
        pytest.skip("Requires the dedicated CRM owner PostgreSQL")
    url = make_url(raw)
    if (url.drivername, url.host, url.port, url.database, url.username) != (
        "postgresql+psycopg", "127.0.0.1", 15441, "crm_ready_h02", "postgres",
    ):
        pytest.fail("Use only the dedicated loopback CRM owner test database")
    schema = f"owners_{uuid4().hex}"
    engine = create_async_engine(url).execution_options(schema_translate_map={
        None: schema, "public": schema, "leads": schema, "sales": schema,
    })
    created = False
    try:
        async with engine.begin() as conn:
            await conn.execute(CreateSchema(schema))
            await conn.run_sync(Base.metadata.create_all, tables=[
                User.__table__, Lead.__table__, LeadItem.__table__, Deal.__table__,
                OutboxEvent.__table__, AuditLog.__table__,
            ])
        created = True
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        try:
            if created:
                async with engine.begin() as conn:
                    await conn.execute(DropSchema(schema, cascade=True))
        finally:
            await engine.dispose()


def _conversion_core(conversion_handler=on_lead_converted):
    bus = OutboxEventBus()
    bus.subscribe("leads.lead.converted", conversion_handler)
    bus.subscribe("sales.deal.created", on_deal_created_from_lead)
    return SimpleNamespace(event_bus=bus, services=SimpleNamespace(event_bus=bus))


async def _seed(factory):
    async with factory() as session:
        owner = User(username="owner", full_name="Synthetic CRM Owner", employee_id=901,
                     department="Продажи", role="sales", status="active")
        lead = Lead(source="site", company="Synthetic owner race", status="routed",
                    assigned_to=owner.full_name)
        session.add_all([owner, lead])
        await session.commit()
        return owner.id, lead.id


async def _wait_for_lock(factory, blocker_pid, waiter_pid, task):
    async with asyncio.timeout(10), factory() as observer:
        while True:
            blocked = await observer.scalar(text(
                "SELECT :blocker = ANY(pg_blocking_pids(:waiter))"
            ), {"blocker": blocker_pid, "waiter": waiter_pid})
            if blocked:
                return
            if task.done():
                # Surface an actual task error instead of disguising it as a missing lock.
                task.result()
                pytest.fail("The competing operation finished without the expected database lock")
            await asyncio.sleep(0.02)


async def _finish_tasks(*tasks):
    for task in tasks:
        if task is not None and not task.done():
            task.cancel()
    await asyncio.gather(*(task for task in tasks if task is not None), return_exceptions=True)


async def _convert(session, lead_id, core):
    try:
        return await convert_lead(lead_id, core=core, session=session)
    finally:
        await session.rollback()


def _pause_first_commit(session, monkeypatch):
    reached, release = asyncio.Event(), asyncio.Event()
    original_commit = session.commit

    async def commit():
        if not reached.is_set():
            reached.set()
            await release.wait()
        await original_commit()

    monkeypatch.setattr(session, "commit", commit)
    return reached, release


async def test_deactivated_owner_is_rechecked_after_conversion_waits(owner_factory):
    owner_id, lead_id = await _seed(owner_factory)
    async with owner_factory() as holder, owner_factory() as converter:
        task = None
        try:
            stale_owner = await converter.get(User, owner_id)
            stale_lead = await converter.get(Lead, lead_id)
            assert stale_owner.status == "active" and stale_lead.status == "routed"
            holder_pid = await holder.scalar(text("SELECT pg_backend_pid()"))
            converter_pid = await converter.scalar(text("SELECT pg_backend_pid()"))
            await holder.execute(update(User).where(User.id == owner_id).values(status="inactive"))

            task = asyncio.create_task(_convert(converter, lead_id, _conversion_core()))
            await _wait_for_lock(owner_factory, holder_pid, converter_pid, task)
            await holder.commit()
            with pytest.raises(HTTPException) as denied:
                await asyncio.wait_for(task, timeout=10)
            assert denied.value.status_code == 422
        finally:
            await _finish_tasks(task)
    async with owner_factory() as verify:
        lead = await verify.get(Lead, lead_id)
        assert lead.status == "routed" and lead.converted_at is None and lead.deal_id is None
        assert (await verify.get(User, owner_id)).status == "inactive"
        assert await verify.scalar(select(func.count()).select_from(OutboxEvent)) == 0
        assert await verify.scalar(select(func.count()).select_from(Deal)) == 0


async def test_owner_share_lock_is_held_until_conversion_commit(owner_factory, monkeypatch):
    owner_id, lead_id = await _seed(owner_factory)
    async with owner_factory() as converter, owner_factory() as deactivator:
        conversion = deactivation = None
        reached, release = _pause_first_commit(converter, monkeypatch)
        try:
            stale_owner = await deactivator.get(User, owner_id)
            assert stale_owner.status == "active"
            converter_pid = await converter.scalar(text("SELECT pg_backend_pid()"))
            deactivator_pid = await deactivator.scalar(text("SELECT pg_backend_pid()"))
            conversion = asyncio.create_task(_convert(converter, lead_id, _conversion_core()))
            await asyncio.wait_for(reached.wait(), timeout=10)

            async def deactivate():
                try:
                    await deactivator.execute(update(User).where(User.id == owner_id).values(status="inactive"))
                    await deactivator.commit()
                finally:
                    await deactivator.rollback()

            deactivation = asyncio.create_task(deactivate())
            await _wait_for_lock(owner_factory, converter_pid, deactivator_pid, deactivation)
            async with owner_factory() as before_commit:
                assert (await before_commit.get(Lead, lead_id)).status == "routed"
                assert await before_commit.scalar(select(func.count()).select_from(OutboxEvent)) == 0
            release.set()
            result, _ = await asyncio.wait_for(asyncio.gather(conversion, deactivation), timeout=10)
            assert result.deal_id is not None
        finally:
            release.set()
            await _finish_tasks(conversion, deactivation)
    async with owner_factory() as verify:
        assert (await verify.get(User, owner_id)).status == "inactive"
        lead = await verify.get(Lead, lead_id)
        deal = await verify.get(Deal, lead.deal_id)
        assert lead.status == "converted" and deal.owner_id == 901
        assert deal.owner == "Synthetic CRM Owner"


async def test_double_conversion_waits_then_rejects_stale_request(owner_factory, monkeypatch):
    owner_id, lead_id = await _seed(owner_factory)
    async with owner_factory() as first, owner_factory() as second:
        first_task = second_task = None
        reached, release = _pause_first_commit(first, monkeypatch)
        core = _conversion_core()
        try:
            stale_lead = await second.get(Lead, lead_id)
            stale_owner = await second.get(User, owner_id)
            assert stale_lead.status == "routed" and stale_owner.status == "active"
            first_pid = await first.scalar(text("SELECT pg_backend_pid()"))
            second_pid = await second.scalar(text("SELECT pg_backend_pid()"))
            first_task = asyncio.create_task(_convert(first, lead_id, core))
            await asyncio.wait_for(reached.wait(), timeout=10)
            second_task = asyncio.create_task(_convert(second, lead_id, core))
            await _wait_for_lock(owner_factory, first_pid, second_pid, second_task)
            release.set()
            with pytest.raises(HTTPException) as duplicate:
                await asyncio.wait_for(second_task, timeout=10)
            assert duplicate.value.status_code == 409
            result = await asyncio.wait_for(first_task, timeout=10)
            assert result.deal_id is not None
        finally:
            release.set()
            await _finish_tasks(first_task, second_task)
    async with owner_factory() as verify:
        lead = await verify.get(Lead, lead_id)
        assert lead.status == "converted" and lead.deal_id is not None
        assert await verify.scalar(select(func.count()).select_from(Deal)) == 1
        events = (await verify.execute(select(OutboxEvent).where(
            OutboxEvent.event_type == "leads.lead.converted",
        ))).scalars().all()
        assert len(events) == 1 and events[0].payload["owner_id"] == 901


async def test_background_relay_allows_pending_then_read_only_resume(owner_factory, monkeypatch):
    _, lead_id = await _seed(owner_factory)
    entered, release = asyncio.Event(), asyncio.Event()

    async def held_conversion(payload, ctx):
        # The real relay already owns the outbox row lock when it calls us.
        entered.set()
        await release.wait()
        await on_lead_converted(payload, ctx)

    core = _conversion_core(held_conversion)
    async with owner_factory() as converter, owner_factory() as background:
        conversion = background_task = None
        committed = False
        original_commit = converter.commit
        original_relay = core.event_bus.relay_once
        converter_deliveries = []

        async def commit_then_start_background():
            nonlocal committed, background_task
            await original_commit()
            if not committed:
                committed = True
                background_task = asyncio.create_task(core.event_bus.relay_once(
                    background, EventContext(background, core.services),
                ))
                await asyncio.wait_for(entered.wait(), timeout=10)

        async def observe_relay(session, ctx, **kwargs):
            delivered = await original_relay(session, ctx, **kwargs)
            if session is converter:
                converter_deliveries.append(delivered)
            return delivered

        monkeypatch.setattr(converter, "commit", commit_then_start_background)
        monkeypatch.setattr(core.event_bus, "relay_once", observe_relay)
        try:
            cached_lead = await converter.get(Lead, lead_id)
            assert cached_lead.status == "routed"
            conversion = asyncio.create_task(_convert(converter, lead_id, core))
            result = await asyncio.wait_for(conversion, timeout=10)
            assert entered.is_set() and not background_task.done()
            assert converter_deliveries == [0]  # Real PostgreSQL SKIP LOCKED, not a stub.
            assert result.status == "converted" and result.deal_id is None
            async with owner_factory() as pending:
                lead = await pending.get(Lead, lead_id)
                assert lead.status == "converted" and lead.deal_id is None
                assert await pending.scalar(select(func.count()).select_from(Deal)) == 0
                event = (await pending.execute(select(OutboxEvent))).scalar_one()
                assert event.event_type == "leads.lead.converted" and event.processed_at is None
                assert event.payload["owner_id"] == 901

            release.set()
            assert await asyncio.wait_for(background_task, timeout=10) == 1
            assert await asyncio.wait_for(core.event_bus.relay_once(
                background, EventContext(background, core.services),
            ), timeout=10) == 1  # The normal sales.deal.created backlink delivery.
        finally:
            release.set()
            await _finish_tasks(conversion, background_task)

    # Resume only reads the lead. No second convert POST/event is needed.
    async with owner_factory() as verify:
        lead = await verify.get(Lead, lead_id)
        assert lead.status == "converted" and lead.deal_id is not None
        deal = await verify.get(Deal, lead.deal_id)
        assert deal.owner_id == 901 and deal.owner == "Synthetic CRM Owner"
        assert await verify.scalar(select(func.count()).select_from(Deal)) == 1
        events = (await verify.execute(select(OutboxEvent))).scalars().all()
        assert sorted(event.event_type for event in events) == [
            "leads.lead.converted", "sales.deal.created",
        ]
        assert all(event.processed_at is not None for event in events)
