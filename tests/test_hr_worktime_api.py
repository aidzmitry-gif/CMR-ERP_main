"""HTTP route, access middleware, commit and approval-boundary acceptance."""
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select

from core.domain.models import Approval, User
from modules.hr import worktime
from modules.hr.models import Employee, WorktimeDay


async def seed(session):
    headers = {}
    for i, (name, role) in enumerate((("clock_worker", "sales"), ("clock_manager", "sales_head"), ("clock_hr", "hr")), 1):
        session.add(Employee(id=i, full_name="Synthetic " + name, status="active"))
        session.add(User(id=i, username=name, full_name="Synthetic " + name, role=role, status="active", employee_id=i))
        headers[name] = {"X-User": name, "X-User-Roles": role}
    await session.commit()
    return headers


async def configure(api, headers):
    result = await api.post("/hr/worktime/policies", headers=headers["clock_hr"], json={
        "employee_id": 1, "manager_id": 2, "effective_from": "2026-10-01", "daily_minutes": 450,
        "weekmask": 31, "reference": "Synthetic contract"})
    assert result.status_code == 200, result.text


async def test_http_commits_commands_and_only_designated_route_can_decide(api, session, monkeypatch):
    headers = await seed(session)
    clock = [datetime(2026, 10, 26, 6, tzinfo=UTC)]
    monkeypatch.setattr(worktime, "now", lambda: clock[0])
    await configure(api, headers)
    start = await api.post("/hr/me/worktime/start", headers=headers["clock_worker"], json={"employee_id": 1, "request_key": str(uuid4())})
    assert start.status_code == 200, start.text
    assert "no-store" in start.headers["cache-control"]
    clock[0] += timedelta(hours=9)
    stopped = await api.post("/hr/me/worktime/end", headers=headers["clock_worker"], json={
        "employee_id": 1, "session_id": start.json()["id"], "request_key": str(uuid4())})
    assert stopped.status_code == 200, stopped.text
    day = await session.scalar(select(WorktimeDay))
    assert day.worked_seconds == 32400
    notice = await api.get("/hr/me/worktime/notices", headers=headers["clock_manager"])
    assert notice.status_code == 200 and "no-store" in notice.headers["cache-control"]
    assert notice.json()["items"][0]["kind"] == "overtime"
    assert (await api.get("/hr/me/worktime/notices", headers=headers["clock_worker"])).json()["items"] == []
    generic = await api.post(f"/approvals/{day.approval_id}/approve", json={"by": "clock_manager", "reason": "Synthetic"})
    assert generic.status_code == 409, generic.text
    wrong = await api.post(f"/hr/worktime/days/{day.id}/decision", headers=headers["clock_hr"], json={"approved": True, "reason": "Synthetic review"})
    assert wrong.status_code == 403
    accepted = await api.post(f"/hr/worktime/days/{day.id}/decision", headers=headers["clock_manager"], json={"approved": True, "reason": "Synthetic review"})
    assert accepted.status_code == 200, accepted.text
    sheet = await api.get("/hr/worktime/timesheet?period=2026-10", headers=headers["clock_worker"])
    assert sheet.json()["items"][0]["credited_minutes"] == 540
    assert (await session.get(Approval, day.approval_id)).status == "approved"
    assert (await api.get("/hr/me/worktime/notices", headers=headers["clock_manager"])).json()["items"] == []


async def test_worktime_does_not_open_hr_or_unbound_identity(api, session):
    headers = await seed(session)
    await configure(api, headers)
    context = await api.get("/hr/me/worktime", headers=headers["clock_worker"])
    assert context.status_code == 200 and context.json()["employee"]["id"] == 1
    assert (await api.get("/hr/employees", headers=headers["clock_worker"])).status_code == 403
    assert (await api.get("/hr/worktime/settings", headers=headers["clock_worker"])).status_code == 403
    for role in ("onboarding", "identity_provisioner", "crm_invitation_operator", ""):
        denied = await api.post("/hr/me/worktime/start", headers={"X-User": "clock_worker", "X-User-Roles": role}, json={"employee_id": 1, "request_key": str(uuid4())})
        assert denied.status_code == 403, (role, denied.text)
    unknown = await api.get("/hr/me/worktime", headers={"X-User": "unbound", "X-User-Roles": "director"})
    assert unknown.status_code == 403


async def test_http_rejected_identity_and_payload_cannot_mutate_another_employee(api, session):
    headers = await seed(session)
    await configure(api, headers)
    wrong = await api.post("/hr/me/worktime/start", headers=headers["clock_worker"], json={"employee_id": 2, "request_key": str(uuid4())})
    assert wrong.status_code == 403
    injected = await api.post("/hr/me/worktime/start", headers=headers["clock_worker"], json={"employee_id": 1, "request_key": str(uuid4()), "started_at": "2000-01-01T00:00:00Z"})
    assert injected.status_code == 422
    assert (await api.get("/hr/me/worktime", headers=headers["clock_worker"])).json()["session"] is None
