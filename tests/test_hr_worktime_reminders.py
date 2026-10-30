# ruff: noqa: F811 -- imported test fixture is requested by pytest.
from datetime import timedelta
from types import SimpleNamespace

from sqlalchemy import func, select

from modules.hr import worktime as w
from modules.hr import worktime_reminders as reminders
from modules.hr.models import WorktimeReminder
from tests.test_hr_worktime import begin, case, finish, policy  # noqa: F401


async def queue(c):
    await reminders.queue_due(c.s, SimpleNamespace(event_bus=c.bus))
    await c.s.commit()


async def test_start_reminder_is_durable_deduplicated_and_employee_only(case):
    await policy(case, start_minute=10 * 60)
    await queue(case)
    await queue(case)
    assert await case.s.scalar(select(func.count()).select_from(WorktimeReminder)) == 1
    own = await reminders.notices(case.s, case.actors["worker"])
    assert len(own["items"]) == 1 and own["items"][0]["kind"] == "start"
    assert (await reminders.notices(case.s, case.actors["other"]))["items"] == []
    assert own["hours_changed"] is False


async def test_no_reminder_without_explicit_schedule_or_before_due(case):
    await policy(case)
    await queue(case)
    assert (await reminders.notices(case.s, case.actors["worker"]))["items"] == []
    await policy(case, effective_from=w.date(2026, 10, 26), start_minute=11 * 60)
    await queue(case)
    assert (await reminders.notices(case.s, case.actors["worker"]))["items"] == []


async def test_starting_day_hides_a_previous_start_reminder(case):
    await policy(case, start_minute=10 * 60)
    await queue(case)
    await w.start(case.s, case.actors["worker"], w.Command(employee_id=1, request_key=w.UUID(int=9)), case.bus)
    await case.s.commit()
    assert (await reminders.notices(case.s, case.actors["worker"]))["items"] == []


async def test_end_reminder_does_not_end_shift_or_add_hours(case):
    _, row = await begin(case)
    case.clock[0] += timedelta(hours=8)
    await queue(case)
    notices = (await reminders.notices(case.s, case.actors["worker"]))["items"]
    assert len(notices) == 1 and notices[0]["kind"] == "end"
    assert (await w.context(case.s, case.actors["worker"]))["session"]["ended_at"] is None
    assert (await w.timesheet(case.s, case.actors["worker"], "2026-10"))["items"] == []
    await w.end(case.s, case.actors["worker"], w.EndCommand(employee_id=1, session_id=row["id"], request_key=w.UUID(int=10)), case.approvals, case.bus)
    await case.s.commit()
    assert (await reminders.notices(case.s, case.actors["worker"]))["items"] == []


async def test_manager_receives_only_own_pending_overtime_and_decision_hides_it(case):
    await finish(case)
    own = (await reminders.notices(case.s, case.actors["manager"]))["items"]
    assert len(own) == 1 and own[0]["kind"] == "overtime"
    assert own[0]["href"] == "/erp/hr/worktime?tab=sheet&period=2026-10"
    assert (await reminders.notices(case.s, case.actors["other"]))["items"] == []
    day_id = int(own[0]["id"].split(":")[1])
    await w.decide(case.s, case.actors["manager"], day_id, w.DecisionInput(approved=True, reason="Synthetic review"), case.approvals)
    await case.s.commit()
    assert (await reminders.notices(case.s, case.actors["manager"]))["items"] == []


async def test_absence_suppresses_start_reminder(case):
    await policy(case, start_minute=10 * 60)
    await w.absence(case.s, case.actors["hr"], w.AbsenceInput(employee_id=1, request_key=w.UUID(int=11),
        work_date=w.date(2026, 10, 26), code="О", reference="Synthetic leave"))
    await case.s.commit()
    await queue(case)
    assert (await reminders.notices(case.s, case.actors["worker"]))["items"] == []
