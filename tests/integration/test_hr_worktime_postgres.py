# ruff: noqa: F811 -- imported pytest fixture is requested by name.
"""Native row locks, atomic rollback and immutable worktime history."""
import asyncio
import os
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select, text

from core.domain.models import Approval, OutboxEvent, User
from core.services.approvals import ApprovalService
from core.services.auth import CurrentUser
from core.services.eventbus import OutboxEventBus
from modules.hr import worktime as w
from modules.hr import worktime_reminders
from modules.hr.models import Employee, WorkSession, WorktimeDay, WorktimeReminder
from tests.accounting.test_postgres import pg_factory  # noqa: F401

pytestmark = pytest.mark.integration


async def seed(factory, monkeypatch):
    clock = [datetime(2026, 10, 26, 8, tzinfo=UTC)]
    monkeypatch.setattr(w, "now", lambda: clock[0])
    actors = {"worker": CurrentUser("worker", ["sales"]), "manager": CurrentUser("manager", ["sales_head"]),
              "hr": CurrentUser("hr", ["hr"])}
    async with factory() as session:
        for index, (name, actor) in enumerate(actors.items(), 1):
            session.add(Employee(id=index, full_name="Synthetic " + name, status="active"))
            session.add(User(id=index, username=name, full_name="Synthetic " + name,
                             role=actor.roles[0], employee_id=index, status="active"))
        await session.commit()
        await w.configure(session, actors["hr"], w.PolicyInput(employee_id=1, manager_id=2,
            effective_from=date(2026, 10, 1), daily_minutes=480, weekmask=31, reference="Synthetic contract"))
        await session.commit()
    bus = OutboxEventBus()
    return SimpleNamespace(clock=clock, actors=actors, bus=bus, approvals=ApprovalService(bus))


@pytest.mark.parametrize("same_key", [True, False])
async def test_concurrent_start_serializes_by_bound_employee(pg_factory, monkeypatch, same_key):
    c = await seed(pg_factory, monkeypatch)
    keys = [uuid4(), uuid4()]
    if same_key:
        keys[1] = keys[0]

    async def begin(key):
        async with pg_factory() as session:
            try:
                result = await w.start(session, c.actors["worker"], w.Command(employee_id=1, request_key=key), c.bus)
                await session.commit()
                return result["id"]
            except HTTPException as exc:
                await session.rollback()
                return exc.status_code

    result = await asyncio.wait_for(asyncio.gather(*(begin(key) for key in keys)), timeout=30)
    if same_key:
        assert result[0] == result[1] and result[0] != 409
    else:
        assert result.count(409) == 1
    async with pg_factory() as session:
        assert await session.scalar(select(func.count()).select_from(WorkSession)) == 1
        assert await session.scalar(select(func.count()).select_from(OutboxEvent)) == 1


async def test_concurrent_end_creates_one_day_and_one_approval(pg_factory, monkeypatch):
    c = await seed(pg_factory, monkeypatch)
    async with pg_factory() as session:
        row = await w.start(session, c.actors["worker"], w.Command(employee_id=1, request_key=uuid4()), c.bus)
        await session.commit()
    c.clock[0] += timedelta(hours=9)
    command = w.EndCommand(employee_id=1, request_key=uuid4(), session_id=row["id"])

    async def end():
        async with pg_factory() as session:
            result = await w.end(session, c.actors["worker"], command, c.approvals, c.bus)
            await session.commit()
            return result

    first, second = await asyncio.wait_for(asyncio.gather(end(), end()), timeout=30)
    assert first == second
    async with pg_factory() as session:
        assert await session.scalar(select(func.count()).select_from(WorktimeDay)) == 1
        assert await session.scalar(select(func.count()).select_from(Approval)) == 1
        assert await session.scalar(select(func.count()).select_from(OutboxEvent)) == 3


async def test_end_failure_rolls_back_day_approval_and_closed_status(pg_factory, monkeypatch):
    c = await seed(pg_factory, monkeypatch)
    async with pg_factory() as session:
        row = await w.start(session, c.actors["worker"], w.Command(employee_id=1, request_key=uuid4()), c.bus)
        await session.commit()
    c.clock[0] += timedelta(hours=9)
    command = w.EndCommand(employee_id=1, request_key=uuid4(), session_id=row["id"])

    class Failure:
        def emit(self, *args):
            raise RuntimeError("synthetic failure after persisted day")

    async with pg_factory() as session:
        with pytest.raises(RuntimeError, match="synthetic failure"):
            await w.end(session, c.actors["worker"], command, c.approvals, Failure())
        await session.rollback()
    async with pg_factory() as session:
        assert (await session.get(WorkSession, row["id"])).ended_at is None
        assert await session.scalar(select(func.count()).select_from(WorktimeDay)) == 0
        assert await session.scalar(select(func.count()).select_from(Approval)) == 0
        await w.end(session, c.actors["worker"], command, c.approvals, c.bus)
        await session.commit()


def migration_command(factory, *args):
    url = factory.kw["bind"].url.render_as_string(hide_password=False)
    return subprocess.run([sys.executable, "-m", "alembic", *args],
        cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, timeout=60,
        env={**os.environ, "AIOS_ENVIRONMENT": "dev", "AIOS_DATABASE_URL": url})


async def test_database_protects_recorded_work_and_refuses_lossy_downgrade(pg_factory, monkeypatch):
    c = await seed(pg_factory, monkeypatch)
    async with pg_factory() as session:
        row = await w.start(session, c.actors["worker"], w.Command(employee_id=1, request_key=uuid4()), c.bus)
        await session.commit()
        c.clock[0] += timedelta(hours=9)
        await w.end(session, c.actors["worker"], w.EndCommand(employee_id=1, request_key=uuid4(), session_id=row["id"]),
                    c.approvals, c.bus)
        await session.commit()
        for sql in ["UPDATE hr.worktime_policy SET daily_minutes=1",
                    "UPDATE hr.work_session SET started_at=started_at-interval '1 hour'",
                    "DELETE FROM hr.work_session", "UPDATE hr.worktime_day SET worked_seconds=0"]:
            with pytest.raises(Exception, match="immutable|cannot be deleted"):
                await session.execute(text(sql))
            await session.rollback()
    result = await asyncio.to_thread(migration_command, pg_factory, "downgrade", "0200")
    assert result.returncode != 0 and "Cannot downgrade recorded worktime" in result.stderr
    async with pg_factory() as session:
        assert await session.scalar(text("SELECT version_num FROM alembic_version")) == "0201"
        assert await session.scalar(select(func.count()).select_from(WorktimeDay)) == 1


async def test_empty_migration_roundtrip_retains_one_head(pg_factory):
    result = await asyncio.to_thread(migration_command, pg_factory, "downgrade", "0200")
    assert result.returncode == 0, result.stderr[-1000:]
    async with pg_factory() as session:
        assert await session.scalar(text("SELECT to_regclass('hr.work_session')")) is None
    result = await asyncio.to_thread(migration_command, pg_factory, "upgrade", "head")
    assert result.returncode == 0, result.stderr[-1000:]
    async with pg_factory() as session:
        assert await session.scalar(text("SELECT version_num FROM alembic_version")) == "0201"
        assert await session.scalar(text("SELECT count(*) FROM hr.work_session")) == 0


async def test_competing_core_ticks_do_not_duplicate_reminders(pg_factory, monkeypatch):
    c = await seed(pg_factory, monkeypatch)
    async with pg_factory() as session:
        await w.start(session, c.actors["worker"], w.Command(employee_id=1, request_key=uuid4()), c.bus)
        await session.commit()
    c.clock[0] += timedelta(hours=9)

    async def queue():
        async with pg_factory() as session:
            await worktime_reminders.queue_due(session, SimpleNamespace(event_bus=c.bus))
            await session.commit()

    await asyncio.wait_for(asyncio.gather(queue(), queue()), timeout=30)
    async with pg_factory() as session:
        assert await session.scalar(select(func.count()).select_from(WorktimeReminder)) == 1
        assert await session.scalar(select(func.count()).select_from(OutboxEvent)) == 2
