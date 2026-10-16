"""Only confirmed external employee links identify a call's seller."""
from types import SimpleNamespace

from sqlalchemy import select

from core.domain.models import SyncLink, User
from modules.hr.models import Employee
from modules.sales.access import scope_calls
from modules.sales.calls import record_event, resolve_agent
from modules.sales.models import CallLog


async def bind(session, extension="00101", *, account=False, status="active"):
    employee = Employee(full_name="Synthetic agent", department="Продажи", status=status)
    session.add(employee)
    await session.flush()
    link = SyncLink(entity_type="employee", entity_id=employee.id, system="telephony",
                    external_ref=extension, origin="telephony", direction="in", state="synced")
    session.add(link)
    if account:
        session.add(User(username="synthetic-agent", full_name=employee.full_name,
                         employee_id=employee.id, department="Продажи", role="sales", status="active"))
    await session.flush()
    return employee, link


async def test_confirmed_agent_resolves_employee_not_user_primary_key(session):
    session.add(User(username="unrelated-user", full_name="Unrelated", role="admin", status="active"))
    await session.flush()
    employee, _ = await bind(session, account=True)
    user = await session.scalar(select(User).where(User.username == "synthetic-agent"))
    assert user.id != employee.id
    assert await resolve_agent(session, "00101") == (employee.full_name, employee.id)
    assert await resolve_agent(session, "101") is None
    assert await resolve_agent(session, "00101/other") is None


async def test_display_only_agent_does_not_grant_numeric_ownership(session):
    employee, _ = await bind(session)
    call, _ = await record_event(session, {"call_id": "SYNTHETIC-DISPLAY", "agent_ext": "00101"}, "telephony.call.incoming")
    await session.flush()
    assert call.owner == employee.full_name and call.owner_id is None
    assert not (await session.scalars(scope_calls(select(CallLog), SimpleNamespace(own_only=True, employee_id=employee.id)))).all()


async def test_duplicate_and_inactive_agent_links_fail_closed(session):
    employee, link = await bind(session, status="inactive")
    assert await resolve_agent(session, "00101") is None
    employee.status = "active"
    session.add(SyncLink(entity_type=link.entity_type, entity_id=employee.id, system=link.system,
                         external_ref=link.external_ref, origin=link.origin, direction="in", state="synced"))
    await session.flush()
    assert await resolve_agent(session, "00101") is None


async def test_late_extension_and_repeated_event_update_one_call(session):
    employee, _ = await bind(session, account=True)
    payload = {"call_id": "SYNTHETIC-LATE"}
    call, created = await record_event(session, payload, "telephony.call.incoming")
    assert created and not call.owner
    for _ in range(2):
        same, created = await record_event(session, {**payload, "agent_ext": "00101"}, "telephony.call.answered")
        assert not created and same.id == call.id
    assert call.owner == employee.full_name and call.owner_id == employee.id
    assert len((await session.scalars(select(CallLog))).all()) == 1
