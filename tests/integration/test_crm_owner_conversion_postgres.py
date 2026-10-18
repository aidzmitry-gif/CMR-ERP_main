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
from core.domain.models import AuditLog, Counterparty, OutboxEvent, User
from core.services.crm_access import CrmAccess
from core.services.eventbus import EventContext, OutboxEventBus
from modules.leads.events import on_deal_created_from_lead
from modules.leads.models import Lead, LeadItem
from modules.leads.routes import convert_lead
from modules.sales.events import on_lead_converted
from modules.sales.models import CrmClient, Deal, Stage
from tests.integration.joint_postgres import is_joint_test_url


@pytest_asyncio.fixture
async def owner_factory():
    raw = os.environ.get("CRM_READY_OWNERS_DATABASE_URL")
    if not raw:
        pytest.skip("Requires the dedicated CRM owner PostgreSQL")
    url = make_url(raw)
    if (url.drivername, url.host, url.port, url.database, url.username) != (
        "postgresql+psycopg", "127.0.0.1", 15441, "crm_ready_h02", "postgres",
    ) and not is_joint_test_url(url):
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
                User.__table__, Lead.__table__, LeadItem.__table__,
                Counterparty.__table__, CrmClient.__table__, Deal.__table__,
                OutboxEvent.__table__, AuditLog.__table__, Stage.__table__,
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


async def _seed(factory, aliases=False):
    async with factory() as session:
        owner = User(username="owner", full_name="Synthetic CRM Owner", employee_id=901,
                     department="Продажи", role="sales", status="active")
        lead = Lead(source="site", company="Synthetic owner race", status="routed",
                    assigned_to=owner.full_name)
        session.add_all([owner, lead])
        if aliases:
            session.add(User(username="synthetic-owner-alias", full_name=owner.full_name, employee_id=901,
                             department="Продажи", role="sales", status="active", deal_visibility="own"))
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
        return await convert_lead(lead_id, core=core, session=session, access=CrmAccess("all"))
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


@pytest.mark.parametrize("aliases", [False, True])
async def test_deactivated_owner_is_rechecked_after_conversion_waits(owner_factory, aliases):
    owner_id, lead_id = await _seed(owner_factory, aliases)
    async with owner_factory() as holder, owner_factory() as converter:
        task = None
        try:
            stale_owner = await converter.get(User, owner_id)
            stale_lead = await converter.get(Lead, lead_id)
            assert stale_owner.status == "active" and stale_lead.status == "routed"
            holder_pid = await holder.scalar(text("SELECT pg_backend_pid()"))
            converter_pid = await converter.scalar(text("SELECT pg_backend_pid()"))
            await holder.execute(update(User).where(User.employee_id == 901).values(status="inactive"))

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


@pytest.mark.parametrize("aliases", [False, True])
async def test_owner_share_lock_is_held_until_conversion_commit(owner_factory, monkeypatch, aliases):
    owner_id, lead_id = await _seed(owner_factory, aliases)
    if aliases:
        async with owner_factory() as lookup:
            owner_id = await lookup.scalar(select(User.id).where(User.username == "synthetic-owner-alias"))
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


async def test_renamed_aliases_are_rechecked_after_conversion_waits(owner_factory):
    owner_id, lead_id = await _seed(owner_factory, aliases=True)
    async with owner_factory() as holder, owner_factory() as converter:
        task = None
        try:
            cached = await converter.get(User, owner_id)
            assert cached.full_name == "Synthetic CRM Owner"
            holder_pid = await holder.scalar(text("SELECT pg_backend_pid()"))
            converter_pid = await converter.scalar(text("SELECT pg_backend_pid()"))
            await holder.execute(update(User).where(User.employee_id == 901).values(full_name="Synthetic renamed owner"))
            task = asyncio.create_task(_convert(converter, lead_id, _conversion_core()))
            await _wait_for_lock(owner_factory, holder_pid, converter_pid, task)
            await holder.commit()
            with pytest.raises(HTTPException) as denied:
                await asyncio.wait_for(task, timeout=10)
            assert denied.value.status_code == 422
        finally:
            await _finish_tasks(task)
    async with owner_factory() as verify:
        names = (await verify.execute(select(User.full_name).where(User.employee_id == 901))).scalars().all()
        assert names == ["Synthetic renamed owner", "Synthetic renamed owner"]
        lead = await verify.get(Lead, lead_id)
        assert lead.status == "routed" and lead.converted_at is None and lead.deal_id is None
        assert await verify.scalar(select(func.count()).select_from(Deal)) == 0
        assert await verify.scalar(select(func.count()).select_from(OutboxEvent)) == 0


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



async def test_employee_login_alias_migration_roundtrip(owner_factory):
    import importlib.util
    import re
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect
    from sqlalchemy.exc import IntegrityError

    path = Path(__file__).resolve().parents[2] / "migrations/versions/0195_employee_login_accounts.py"
    spec = importlib.util.spec_from_file_location("synthetic_employee_alias_migration", path)
    version = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(version)
    assert version.revision == "0195" and version.down_revision == "0194"

    def invoke(connection, function):
        version.op = Operations(MigrationContext.configure(connection))
        getattr(version, function)()

    def catalog(connection, schema):
        inspector = inspect(connection)
        return (inspector.get_unique_constraints("app_user", schema=schema),
                inspector.get_indexes("app_user", schema=schema))

    def account(username, email, subject):
        return User(username=username, email=email, keycloak_user_id=subject, employee_id=9900195,
                    full_name="Synthetic migration employee", department="Продажи", role="sales",
                    status="active", deal_visibility="own")

    async with owner_factory() as session:
        connection = await session.connection()
        schema = connection.sync_connection.get_execution_options()["schema_translate_map"][None]
        assert re.fullmatch(r"owners_[0-9a-f]{32}", schema)
        await session.execute(text(f'SET LOCAL search_path TO "{schema}"'))
        assert await session.scalar(text("SELECT current_schema()")) == schema
        assert 160000 <= int(await session.scalar(text("SHOW server_version_num"))) < 170000
        assert await session.scalar(text("SELECT 'app_user'::regclass::oid")) == await session.scalar(
            text("SELECT to_regclass(:qualified)::oid"), {"qualified": f'"{schema}".app_user'},
        )

        # Recreate the actual predecessor contract from 0107, not just an ORM table.
        def predecessor(sync):
            operations = Operations(MigrationContext.configure(sync))
            operations.drop_index("ix_app_user_employee_id", table_name="app_user")
            operations.create_unique_constraint(operations.f("uq_app_user_employee_id"), "app_user", ["employee_id"])
        await connection.run_sync(predecessor)
        original = account("synthetic-primary", "primary@example.invalid", "synthetic-primary-subject")
        session.add(original)
        await session.flush()
        original_id = original.id
        before = dict((await session.execute(select(User.__table__).where(User.id == original_id))).mappings().one())
        constraints, indexes = await connection.run_sync(lambda sync: catalog(sync, schema))
        assert [c["name"] for c in constraints if c["column_names"] == ["employee_id"]] == ["uq_app_user_employee_id"]
        assert not any(i["name"] == "ix_app_user_employee_id" for i in indexes)
        with pytest.raises(IntegrityError):
            async with session.begin_nested():
                session.add(account("synthetic-before", "before@example.invalid", "synthetic-before-subject"))
                await session.flush()

        await connection.run_sync(lambda sync: invoke(sync, "upgrade"))
        assert dict((await session.execute(select(User.__table__).where(User.id == original_id))).mappings().one()) == before
        constraints, indexes = await connection.run_sync(lambda sync: catalog(sync, schema))
        assert not any(c["column_names"] == ["employee_id"] for c in constraints)
        index = next(i for i in indexes if i["name"] == "ix_app_user_employee_id")
        assert index["column_names"] == ["employee_id"] and not index["unique"]
        alias = account("synthetic-alias", "alias@example.invalid", "synthetic-alias-subject")
        session.add(alias)
        await session.flush()
        assert await session.scalar(select(func.count()).select_from(User)) == 2
        for username, email, subject in [
            ("synthetic-primary", "unique-a@example.invalid", "synthetic-unique-a"),
            ("synthetic-unique-b", "primary@example.invalid", "synthetic-unique-b"),
            ("synthetic-unique-c", "unique-c@example.invalid", "synthetic-primary-subject"),
        ]:
            with pytest.raises(IntegrityError):
                async with session.begin_nested():
                    session.add(account(username, email, subject))
                    await session.flush()

        upgraded_catalog = await connection.run_sync(lambda sync: catalog(sync, schema))
        with pytest.raises(RuntimeError, match="Resolve login aliases"):
            async with session.begin_nested():
                await connection.run_sync(lambda sync: invoke(sync, "downgrade"))
        assert await session.scalar(select(func.count()).select_from(User)) == 2
        assert await connection.run_sync(lambda sync: catalog(sync, schema)) == upgraded_catalog
        assert dict((await session.execute(select(User.__table__).where(User.id == original_id))).mappings().one()) == before

        await session.delete(alias)
        await session.flush()
        await connection.run_sync(lambda sync: invoke(sync, "downgrade"))
        constraints, indexes = await connection.run_sync(lambda sync: catalog(sync, schema))
        assert [c["name"] for c in constraints if c["column_names"] == ["employee_id"]] == ["uq_app_user_employee_id"]
        assert not any(i["name"] == "ix_app_user_employee_id" for i in indexes)
        assert any(i["name"] == "uq_app_user_employee_id" and i["unique"] for i in indexes)
        with pytest.raises(IntegrityError):
            async with session.begin_nested():
                session.add(account("synthetic-after", "after@example.invalid", "synthetic-after-subject"))
                await session.flush()
        assert dict((await session.execute(select(User.__table__).where(User.id == original_id))).mappings().one()) == before
        await session.commit()

    async with owner_factory() as verify:
        await verify.execute(text(f'SET LOCAL search_path TO "{schema}"'))
        assert await verify.scalar(text("SELECT current_schema()")) == schema
        assert await verify.scalar(select(func.count()).select_from(User)) == 1
        assert dict((await verify.execute(select(User.__table__).where(User.id == original_id))).mappings().one()) == before
        connection = await verify.connection()
        constraints, indexes = await connection.run_sync(lambda sync: catalog(sync, schema))
        assert [c["name"] for c in constraints if c["column_names"] == ["employee_id"]] == ["uq_app_user_employee_id"]
        assert not any(i["name"] == "ix_app_user_employee_id" for i in indexes)
