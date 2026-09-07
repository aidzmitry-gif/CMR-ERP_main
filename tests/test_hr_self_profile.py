"""Self service cannot widen onboarding or expose another employee's data."""
import json

import pytest
from sqlalchemy import select

from core.domain.models import AuditLog, User
from core.runtime.identity_routes import InviteEmployeeIn, _username
from modules.hr.models import Employee, EmployeeProfile


async def employee_user(session, username="self", role="onboarding", status="onboarding"):
    employee = Employee(full_name="Тестовый сотрудник", department="Продажи", position="Менеджер")
    session.add(employee)
    await session.flush()
    user = User(username=username, full_name=employee.full_name, employee_id=employee.id,
                role=role, status=status)
    session.add(user)
    await session.commit()
    return employee, user, {"X-User": username, "X-User-Roles": role}


@pytest.mark.asyncio
async def test_onboarding_can_fill_own_card_without_activating_or_reading_hr(api, session):
    employee, user, headers = await employee_user(session)
    response = await api.get("/hr/me/profile", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "not_started"
    assert response.headers["cache-control"] == "no-store"
    payload = {"revision": 0, "birth_date": "1990-01-01", "children_birth_dates": ["2015-02-03"],
               "phone": "+375 29 0000000", "status": "submitted"}
    saved = await api.put("/hr/me/profile", headers=headers, json=payload)
    assert saved.status_code == 200, saved.text
    assert saved.json()["revision"] == 1
    assert saved.json()["children_birth_dates"] == ["2015-02-03"]
    await session.refresh(user)
    assert user.role == "onboarding" and user.status == "onboarding"
    for path in ["/hr/employees", f"/hr/employee-profiles/{employee.id}", "/sales/board", "/system/users"]:
        assert (await api.get(path, headers=headers)).status_code == 403
    logs = (await session.execute(select(AuditLog).where(AuditLog.action == "hr.profile.self_updated"))).scalars().all()
    serialized = json.dumps([log.detail for log in logs])
    assert "1990" not in serialized and "+375" not in serialized and "2015" not in serialized


@pytest.mark.asyncio
async def test_ownership_private_read_and_public_status(api, session):
    employee, _, headers = await employee_user(session, role="sales", status="active")
    foreign, _, foreign_headers = await employee_user(session, username="foreign", role="sales", status="active")
    payload = {"revision": 0, "birth_date": "1991-01-01", "city": "Минск"}
    assert (await api.put("/hr/me/profile", headers=headers, json=payload)).status_code == 200
    for injected in [{"employee_id": foreign.id}, {"role": "director"}, {"department": "Руководство"}]:
        response = await api.put("/hr/me/profile", headers=headers, json={**payload, **injected, "revision": 1})
        assert response.status_code == 422
    assert (await api.get("/hr/me/profile", headers=foreign_headers)).json()["birth_date"] is None
    assert await session.get(EmployeeProfile, foreign.id) is None
    for role in ["sales", "director", "commercial", "admin", "onboarding", "identity_provisioner"]:
        assert (await api.get(f"/hr/employee-profiles/{employee.id}", headers={"X-User-Roles": role})).status_code == 403
    read = await api.get(f"/hr/employee-profiles/{employee.id}", headers={"X-User-Roles": "hr"})
    assert read.status_code == 200 and read.json()["birth_date"] == "1991-01-01"
    assert read.headers["cache-control"] == "no-store"
    listing = await api.get("/hr/employees")
    assert listing.status_code == 200
    assert "1991" not in listing.text and "Минск" not in listing.text and "birth_date" not in listing.text
    assert any(row["id"] == employee.id and row["profile_status"] == "draft" for row in listing.json())


@pytest.mark.asyncio
async def test_private_fields_can_be_cleared_and_stale_update_is_rejected(api, session):
    _, _, headers = await employee_user(session)
    first = await api.put("/hr/me/profile", headers=headers, json={"revision": 0, "birth_date": "1990-01-01", "children_birth_dates": []})
    assert first.status_code == 200
    assert first.json()["children_birth_dates"] == []
    stale = await api.put("/hr/me/profile", headers=headers, json={"revision": 0, "city": "lost update"})
    assert stale.status_code == 409
    cleared = await api.put("/hr/me/profile", headers=headers, json={"revision": 1, "status": "submitted"})
    assert cleared.status_code == 200
    assert cleared.json()["birth_date"] is None and cleared.json()["children_birth_dates"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("patch", [
    {"birth_date": "2999-01-01"}, {"birth_date": "1899-01-01"},
    {"birth_date": "2020-01-01", "children_birth_dates": ["2010-01-01"]},
    {"children_birth_dates": ["2025-02-30"]}, {"children_birth_dates": ["2020-01-01"] * 31},
    {"phone": "1" * 41},
])
async def test_invalid_dates_or_unbounded_fields_are_not_saved(api, session, patch):
    employee, _, headers = await employee_user(session)
    response = await api.put("/hr/me/profile", headers=headers, json={"revision": 0, **patch})
    assert response.status_code == 422
    assert await session.get(EmployeeProfile, employee.id) is None


@pytest.mark.asyncio
async def test_revoked_unlinked_guest_and_service_users_cannot_edit(api, session):
    employee, user, headers = await employee_user(session, role="sales", status="suspended")
    for h in [headers, {"X-User": "nobody", "X-User-Roles": "sales"}, {"X-User-Roles": ""},
              {"X-User": "self", "X-User-Roles": "identity_provisioner"}]:
        assert (await api.put("/hr/me/profile", headers=h, json={"revision": 0})).status_code == 403
    user.status = "active"
    employee.status = "inactive"
    await session.commit()
    assert (await api.get("/hr/me/profile", headers=headers)).status_code == 403


def test_cyrillic_login_uses_email_and_preserves_canonical_latin_login():
    data = {"employee_id": 1, "email": "dtenergo@example.com", "department": "Руководство", "role": "director"}
    assert _username(InviteEmployeeIn(**data, username="ХарьковичД")) == "dtenergo"
    assert _username(InviteEmployeeIn(**data, username="dima.old")) == "dima.old"


@pytest.mark.asyncio
async def test_oidc_subject_wins_over_forged_username_role_and_revocation(session, monkeypatch):
    from types import SimpleNamespace

    from httpx import ASGITransport, AsyncClient
    from sqlalchemy.ext.asyncio import async_sessionmaker

    import core.services.auth as auth
    from core.runtime.app import create_app
    from core.runtime.deps import get_session

    own, linked, _ = await employee_user(session, username="renamed", role="sales", status="active")
    other, _, _ = await employee_user(session, username="forged", role="sales", status="active")
    linked.keycloak_user_id = "synthetic-stable-subject"
    await session.commit()
    app = create_app()
    app.state.core.services.db.session_factory = async_sessionmaker(session.bind, expire_on_commit=False)

    async def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    monkeypatch.setattr(auth, "get_settings", lambda: SimpleNamespace(auth_mode="oidc"))
    monkeypatch.setattr(auth, "_get_authenticator", lambda settings: SimpleNamespace(
        validate=lambda token: auth.CurrentUser("old-name", ["sales"], "synthetic-stable-subject")))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        headers = {"Authorization": "Bearer synthetic", "X-User": "forged", "X-User-Roles": "director"}
        result = await client.put("/hr/me/profile", headers=headers, json={"revision": 0, "city": "Own city"})
        assert result.status_code == 200, result.text
        assert result.json()["employee_id"] == own.id
        assert await session.get(EmployeeProfile, other.id) is None
        assert (await client.get("/hr/employees", headers=headers)).status_code == 403
        linked.status = "suspended"
        await session.commit()
        assert (await client.get("/hr/me/profile", headers=headers)).status_code == 403
