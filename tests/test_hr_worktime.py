"""Synthetic worktime acceptance; no company records or payroll writes."""
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.db.base import Base
from core.domain.models import Approval, AuditLog, OutboxEvent, User
from core.services.approvals import ApprovalService, ModuleApprovalRequired
from core.services.auth import CurrentUser
from core.services.eventbus import OutboxEventBus
from modules.hr import worktime as w
from modules.hr.models import (
    Employee,
    WorkPresence,
    WorkSession,
    WorktimeDay,
    WorktimePolicy,
    WorktimeReminder,
)


@pytest_asyncio.fixture
async def case(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", execution_options={"schema_translate_map": {"hr": None}})
    tables = [Employee.__table__, User.__table__, Approval.__table__, AuditLog.__table__, OutboxEvent.__table__,
              WorktimePolicy.__table__, WorkSession.__table__, WorktimeDay.__table__, WorkPresence.__table__, WorktimeReminder.__table__]
    async with engine.begin() as connection:
        await connection.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
    clock = [datetime(2026, 10, 26, 8, tzinfo=UTC)]
    monkeypatch.setattr(w, "now", lambda: clock[0])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        roles = {"worker": "sales", "manager": "sales_head", "hr": "hr", "other": "sales_head"}
        for index, (name, role) in enumerate(roles.items(), 1):
            session.add(Employee(id=index, full_name="Synthetic " + name, department="Synthetic", status="active"))
            session.add(User(id=index, username=name, full_name="Synthetic " + name,
                             employee_id=index, role=role, status="active"))
        await session.commit()
        bus = OutboxEventBus()
        yield SimpleNamespace(s=session, clock=clock, bus=bus, approvals=ApprovalService(bus),
                              actors={name: CurrentUser(name, [role]) for name, role in roles.items()})
    await engine.dispose()


async def policy(c, **changes):
    data = dict(employee_id=1, effective_from=date(2026, 10, 1), daily_minutes=480,
                weekmask=31, manager_id=2, reference="Synthetic contract")
    data.update(changes)
    result = await w.configure(c.s, c.actors["hr"], w.PolicyInput(**data))
    await c.s.commit()
    return result


async def begin(c):
    await policy(c)
    command = w.Command(employee_id=1, request_key=uuid4())
    result = await w.start(c.s, c.actors["worker"], command, c.bus)
    await c.s.commit()
    return command, result


async def finish(c, hours=9):
    _, row = await begin(c)
    c.clock[0] += timedelta(hours=hours)
    command = w.EndCommand(employee_id=1, request_key=uuid4(), session_id=row["id"])
    result = await w.end(c.s, c.actors["worker"], command, c.approvals, c.bus)
    await c.s.commit()
    return command, result


async def test_unconfigured_context_does_not_invent_norm_or_session(case):
    result = await w.context(case.s, case.actors["worker"])
    assert result["policy"] is result["session"] is None
    assert result["presence_affects_hours"] is False


async def test_configured_contract_is_returned(case):
    saved = await policy(case, daily_minutes=450)
    result = await w.context(case.s, case.actors["worker"])
    assert result["policy"]["id"] == saved["id"]
    assert result["policy"]["daily_minutes"] == 450


async def test_worker_cannot_configure_norm(case):
    data = w.PolicyInput(employee_id=1, effective_from=date(2026, 10, 1), daily_minutes=480,
                         weekmask=31, manager_id=2, reference="Synthetic contract")
    with pytest.raises(HTTPException) as error:
        await w.configure(case.s, case.actors["worker"], data)
    assert error.value.status_code == 403
    assert await case.s.scalar(select(func.count()).select_from(WorktimePolicy)) == 0


async def test_policy_cannot_assign_employee_as_own_manager(case):
    with pytest.raises(HTTPException, match="собственную"):
        await policy(case, manager_id=1)


async def test_same_effective_policy_cannot_be_overwritten(case):
    await policy(case)
    with pytest.raises(HTTPException, match="уже сохранена"):
        await policy(case, daily_minutes=420)
    assert await case.s.scalar(select(func.count()).select_from(WorktimePolicy)) == 1


async def test_identical_policy_retry_does_not_duplicate_history(case):
    first = await policy(case)
    assert await policy(case) == first
    assert await case.s.scalar(select(func.count()).select_from(WorktimePolicy)) == 1


async def test_former_manager_sees_only_days_assigned_to_them(case):
    await finish(case)
    await policy(case, effective_from=date(2026, 10, 27), manager_id=4)
    case.clock[0] = datetime(2026, 10, 28, 8, tzinfo=UTC)
    old_manager = await w.timesheet(case.s, case.actors["manager"], "2026-10")
    assert len(old_manager["items"]) == 1
    assert old_manager["items"][0]["can_decide"] is True
    assert {r["employee"]["id"] for r in (await w.board(case.s, case.actors["manager"]))["items"]} == {2}


async def test_start_requires_explicit_contract(case):
    with pytest.raises(HTTPException, match="ещё не настроены"):
        await w.start(case.s, case.actors["worker"], w.Command(employee_id=1, request_key=uuid4()), case.bus)
    assert await case.s.scalar(select(func.count()).select_from(WorkSession)) == 0


async def test_start_replay_keeps_one_session_and_outbox_event(case):
    command, first = await begin(case)
    second = await w.start(case.s, case.actors["worker"], command, case.bus)
    assert first["id"] == second["id"]
    assert await case.s.scalar(select(func.count()).select_from(WorkSession)) == 1
    assert await case.s.scalar(select(func.count()).select_from(OutboxEvent)) == 1


async def test_other_start_key_cannot_open_parallel_shift(case):
    await begin(case)
    with pytest.raises(HTTPException, match="уже начат"):
        await w.start(case.s, case.actors["worker"], w.Command(employee_id=1, request_key=uuid4()), case.bus)


async def test_presence_is_separate_from_button_to_button_hours(case):
    _, row = await begin(case)
    case.clock[0] += timedelta(hours=3)
    context = await w.context(case.s, case.actors["worker"])
    assert context["session"]["present"] is False
    assert context["session"]["elapsed_seconds"] == 10800
    seen = await w.heartbeat(case.s, case.actors["worker"], row["id"])
    assert seen["present"] is True and seen["elapsed_seconds"] == 10800


async def test_end_replay_keeps_one_day_and_one_approval(case):
    command, first = await finish(case)
    events = await case.s.scalar(select(func.count()).select_from(OutboxEvent))
    second = await w.end(case.s, case.actors["worker"], command, case.approvals, case.bus)
    assert first == second
    assert await case.s.scalar(select(func.count()).select_from(WorktimeDay)) == 1
    assert await case.s.scalar(select(func.count()).select_from(Approval)) == 1
    assert await case.s.scalar(select(func.count()).select_from(OutboxEvent)) == events


async def test_changed_end_key_does_not_rewrite_closed_shift(case):
    command, _ = await finish(case)
    with pytest.raises(HTTPException, match="другим запросом"):
        await w.end(case.s, case.actors["worker"],
                    w.EndCommand(employee_id=1, request_key=uuid4(), session_id=command.session_id), case.approvals, case.bus)


async def test_foreign_employee_cannot_end_shift(case):
    _, row = await begin(case)
    with pytest.raises(HTTPException) as error:
        await w.end(case.s, case.actors["other"],
                    w.EndCommand(employee_id=4, request_key=uuid4(), session_id=row["id"]), case.approvals, case.bus)
    assert error.value.status_code == 404
    assert (await case.s.get(WorkSession, row["id"])).ended_at is None


async def test_revoked_identity_cannot_continue_shift(case):
    _, row = await begin(case)
    (await case.s.get(User, 1)).status = "blocked"
    await case.s.commit()
    with pytest.raises(HTTPException) as error:
        await w.heartbeat(case.s, case.actors["worker"], row["id"])
    assert error.value.status_code == 403


async def test_inactive_employee_cannot_start(case):
    await policy(case)
    (await case.s.get(Employee, 1)).status = "inactive"
    await case.s.commit()
    with pytest.raises(HTTPException) as error:
        await w.start(case.s, case.actors["worker"], w.Command(employee_id=1, request_key=uuid4()), case.bus)
    assert error.value.status_code == 403


async def test_overnight_shift_splits_actual_calendar_days(case):
    case.clock[0] = datetime(2026, 10, 26, 20, tzinfo=UTC)
    await finish(case, hours=6)
    rows = (await case.s.scalars(select(WorktimeDay).order_by(WorktimeDay.work_date))).all()
    assert [(r.work_date, r.worked_seconds) for r in rows] == [
        (date(2026, 10, 26), 3600), (date(2026, 10, 27), 18000)]


async def test_pending_overtime_does_not_add_unapproved_hours(case):
    await finish(case, hours=9.5)
    sheet = await w.timesheet(case.s, case.actors["worker"], "2026-10")
    row = sheet["items"][0]
    assert row["hours"] == "8" and row["extra_hours"] == "1"
    assert row["approval_status"] == "pending" and sheet["payroll_posted"] is False


async def test_designated_manager_approves_and_replays_without_duplicate(case):
    await finish(case)
    day = await case.s.scalar(select(WorktimeDay))
    decision = w.DecisionInput(approved=True, reason="Synthetic review")
    first = await w.decide(case.s, case.actors["manager"], day.id, decision, case.approvals)
    await case.s.commit()
    events = await case.s.scalar(select(func.count()).select_from(OutboxEvent))
    assert await w.decide(case.s, case.actors["manager"], day.id, decision, case.approvals) == first
    assert await case.s.scalar(select(func.count()).select_from(OutboxEvent)) == events
    assert (await w.timesheet(case.s, case.actors["worker"], "2026-10"))["items"][0]["hours"] == "9"


async def test_other_manager_cannot_approve(case):
    await finish(case)
    day = await case.s.scalar(select(WorktimeDay))
    with pytest.raises(HTTPException) as error:
        await w.decide(case.s, case.actors["other"], day.id,
                       w.DecisionInput(approved=True, reason="Not assigned"), case.approvals)
    assert error.value.status_code == 403


async def test_generic_approval_service_cannot_bypass_worktime_authorization(case):
    await finish(case)
    approval = await case.s.scalar(select(Approval))
    with pytest.raises(ModuleApprovalRequired):
        await case.approvals.decide(case.s, approval, True, "spoofed manager")
    assert approval.status == "pending"


async def test_rejected_overtime_keeps_only_contract_hours(case):
    await finish(case)
    day = await case.s.scalar(select(WorktimeDay))
    await w.decide(case.s, case.actors["manager"], day.id,
                   w.DecisionInput(approved=False, reason="Synthetic rejection"), case.approvals)
    row = (await w.timesheet(case.s, case.actors["worker"], "2026-10"))["items"][0]
    assert row["hours"] == "8" and row["approval_status"] == "rejected"


async def test_explicit_absence_code_replays_without_starting_session(case):
    await policy(case)
    data = w.AbsenceInput(request_key=uuid4(), employee_id=1, work_date=date(2026, 10, 25),
                          code="О", reference="Synthetic approved leave")
    first = await w.absence(case.s, case.actors["hr"], data)
    await case.s.commit()
    assert await w.absence(case.s, case.actors["hr"], data) == first
    assert await case.s.scalar(select(func.count()).select_from(WorkSession)) == 0
    assert (await case.s.scalar(select(WorktimeDay))).code == "О"


async def test_absence_cannot_replace_recorded_work(case):
    await finish(case, hours=7)
    with pytest.raises(HTTPException, match="уже есть запись"):
        await w.absence(case.s, case.actors["hr"], w.AbsenceInput(request_key=uuid4(), employee_id=1,
            work_date=date(2026, 10, 26), code="Б", reference="Synthetic sick leave"))


async def test_new_contract_does_not_rewrite_recorded_day(case):
    await finish(case, hours=7)
    await policy(case, effective_from=date(2026, 10, 27), daily_minutes=360)
    row = (await w.timesheet(case.s, case.actors["worker"], "2026-10"))["items"][0]
    assert row["norm_minutes"] == 480 and row["hours"] == "7"


async def test_manager_and_worker_cannot_read_unassigned_employees(case):
    await policy(case)
    manager = await w.board(case.s, case.actors["manager"])
    other = await w.board(case.s, case.actors["other"])
    assert {r["employee"]["id"] for r in manager["items"]} == {1, 2}
    assert {r["employee"]["id"] for r in other["items"]} == {4}


async def test_stale_employee_identity_cannot_start_for_new_login(case):
    await policy(case)
    with pytest.raises(HTTPException) as error:
        await w.start(case.s, case.actors["worker"], w.Command(employee_id=4, request_key=uuid4()), case.bus)
    assert error.value.status_code == 403
    assert await case.s.scalar(select(func.count()).select_from(WorkSession)) == 0


async def test_presence_without_started_day_never_creates_timesheet_hours(case):
    await w.presence(case.s, case.actors["worker"])
    await case.s.commit()
    rows = (await w.board(case.s, case.actors["worker"]))["items"]
    assert rows[0]["present"] is True and rows[0]["session"] is None
    assert (await w.timesheet(case.s, case.actors["worker"], "2026-10"))["items"] == []
    case.clock[0] += timedelta(seconds=91)
    assert (await w.board(case.s, case.actors["worker"]))["items"][0]["present"] is False
