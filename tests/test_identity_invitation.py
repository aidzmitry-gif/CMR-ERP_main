"""Приглашение сотрудника: HR-связь, department-role gate и Keycloak Admin API."""
from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from core.domain.models import AuditLog, User
from core.runtime.app import create_app
from core.runtime.deps import get_session
from core.runtime.identity_routes import get_identity_gateway
from core.services.auth import CurrentUser, has_permission
from core.services.keycloak_admin import KeycloakAdminClient, KeycloakInvitation
from modules.hr.models import Employee


class FakeIdentityGateway:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def invite_user(self, **kwargs) -> KeycloakInvitation:
        self.calls.append(kwargs)
        return KeycloakInvitation(
            user_id="kc-user-42",
            username=kwargs["username"],
            email=kwargs["email"],
            role=kwargs["role"],
            actions=("VERIFY_EMAIL", "UPDATE_PASSWORD"),
            reused=False,
        )


@pytest_asyncio.fixture
async def identity_api(session):
    app = create_app()
    gateway = FakeIdentityGateway()

    async def _session():
        yield session

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_identity_gateway] = lambda: gateway
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-User": "owner", "X-User-Roles": "director"},
    ) as client:
        yield client, gateway


@pytest.mark.asyncio
async def test_invite_employee_persists_identity_and_audit(session, identity_api):
    api, gateway = identity_api
    employee = Employee(full_name="Петров Пётр", position="Менеджер", department="")
    session.add(employee)
    await session.commit()
    await session.refresh(employee)

    response = await api.post(
        "/system/users/invite",
        json={
            "employee_id": employee.id,
            "email": " Petr@example.by ",
            "department": "Продажи",
            "role": "sales",
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["username"] == "petr"
    assert body["email"] == "petr@example.by"
    assert body["employee_id"] == employee.id
    assert body["department"] == "Продажи" and body["role"] == "sales"
    assert body["keycloak_user_id"] == "kc-user-42" and body["status"] == "invited"
    assert gateway.calls == [
        {
            "username": "petr",
            "full_name": "Петров Пётр",
            "email": "petr@example.by",
            "department": "Продажи",
            "role": "sales",
        }
    ]

    user = (await session.execute(select(User).where(User.employee_id == employee.id))).scalar_one()
    audit = (
        await session.execute(select(AuditLog).where(AuditLog.action == "identity.user.invited"))
    ).scalar_one()
    await session.refresh(employee)
    assert user.email == "petr@example.by" and employee.department == "Продажи"
    assert audit.actor == "owner" and audit.detail["role"] == "sales"


@pytest.mark.asyncio
async def test_invite_rejects_role_from_another_department(session, identity_api):
    api, gateway = identity_api
    employee = Employee(full_name="Сотрудник", department="Продажи")
    session.add(employee)
    await session.commit()
    await session.refresh(employee)

    response = await api.post(
        "/system/users/invite",
        json={
            "employee_id": employee.id,
            "email": "user@example.by",
            "department": "Продажи",
            "role": "finance",
        },
    )
    assert response.status_code == 422
    assert gateway.calls == []


@pytest.mark.asyncio
async def test_invite_requires_identity_permission(session, identity_api):
    api, gateway = identity_api
    employee = Employee(full_name="Сотрудник", department="Продажи")
    session.add(employee)
    await session.commit()
    await session.refresh(employee)

    response = await api.post(
        "/system/users/invite",
        headers={"X-User-Roles": "sales"},
        json={
            "employee_id": employee.id,
            "email": "user@example.by",
            "department": "Продажи",
            "role": "sales",
        },
    )
    assert response.status_code == 403
    assert gateway.calls == []


@pytest.mark.asyncio
async def test_identity_provisioner_can_invite_but_has_no_system_write(session, identity_api):
    api, gateway = identity_api
    employee = Employee(full_name="Сервисный сотрудник", department="")
    session.add(employee)
    await session.commit()
    await session.refresh(employee)

    response = await api.post(
        "/system/users/invite",
        headers={"X-User": "service-account-aios-inviter", "X-User-Roles": "identity_provisioner"},
        json={
            "employee_id": employee.id,
            "email": "service.employee@example.by",
            "department": "Продажи",
            "role": "sales",
        },
    )

    assert response.status_code == 201, response.text
    assert gateway.calls[0]["username"] == "service.employee"
    core = api._transport.app.state.core
    service_user = CurrentUser("service-account-aios-inviter", ["identity_provisioner"])
    assert has_permission(core, service_user, "identity.invite") is True
    assert has_permission(core, service_user, "system.write") is False


@pytest.mark.asyncio
async def test_reinvite_is_idempotent_but_role_change_is_blocked(session, identity_api):
    api, gateway = identity_api
    employee = Employee(full_name="Сотрудник", department="Продажи")
    session.add(employee)
    await session.commit()
    await session.refresh(employee)
    payload = {
        "employee_id": employee.id,
        "email": "stable@example.by",
        "department": "Продажи",
        "role": "sales",
        "username": "stable",
    }

    first = await api.post("/system/users/invite", json=payload)
    second = await api.post("/system/users/invite", json=payload)
    changed = await api.post(
        "/system/users/invite", json={**payload, "role": "sales_head"}
    )

    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert changed.status_code == 409
    assert len(gateway.calls) == 2


@pytest.mark.asyncio
async def test_keycloak_client_assigns_role_and_requests_one_time_actions():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        path = request.url.path
        if path.endswith("/protocol/openid-connect/token"):
            return httpx.Response(200, json={"access_token": "service-token"})
        if path.endswith("/admin/realms/aios/users") and request.method == "POST":
            payload = json.loads(request.content)
            assert payload["requiredActions"] == ["VERIFY_EMAIL", "UPDATE_PASSWORD"]
            assert payload["attributes"] == {"department": ["Продажи"]}
            assert payload["firstName"] == "Пётр"
            assert payload["lastName"] == "Петров"
            return httpx.Response(201, headers={"location": "http://kc/users/user-1"})
        if path.endswith("/admin/realms/aios/roles/sales"):
            return httpx.Response(200, json={"id": "role-1", "name": "sales"})
        if path.endswith("/role-mappings/realm"):
            return httpx.Response(204)
        if path.endswith("/execute-actions-email"):
            assert json.loads(request.content) == ["VERIFY_EMAIL", "UPDATE_PASSWORD"]
            assert request.url.params["client_id"] == "aios-backend"
            assert request.url.params["redirect_uri"] == "https://erp.example.by/crm/deals"
            assert request.url.params["lifespan"] == "43200"
            return httpx.Response(204)
        return httpx.Response(404)

    settings = SimpleNamespace(
        keycloak_admin_base_url="http://keycloak:8080",
        keycloak_admin_realm="aios",
        keycloak_admin_client_id="crm-inviter",
        keycloak_admin_client_secret="not-logged",
        keycloak_invite_client_id="aios-backend",
        keycloak_invite_redirect_uri="https://erp.example.by/crm/deals",
        keycloak_invite_lifespan_seconds=43_200,
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await KeycloakAdminClient(settings, client=http).invite_user(
            username="petrov",
            full_name="Петров Пётр",
            email="petrov@example.by",
            department="Продажи",
            role="sales",
        )

    assert result.user_id == "user-1"
    assert result.actions == ("VERIFY_EMAIL", "UPDATE_PASSWORD")
    assert [request.method for request in seen] == ["POST", "POST", "GET", "POST", "PUT"]


@pytest.mark.asyncio
async def test_keycloak_client_repairs_reused_user_profile_before_invite():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        path = request.url.path
        if path.endswith("/protocol/openid-connect/token"):
            return httpx.Response(200, json={"access_token": "service-token"})
        if path.endswith("/admin/realms/aios/users") and request.method == "POST":
            return httpx.Response(409)
        if path.endswith("/admin/realms/aios/users") and request.method == "GET":
            return httpx.Response(
                200,
                json=[{"id": "user-1", "username": "petrov", "email": "petrov@example.by"}],
            )
        if path.endswith("/admin/realms/aios/users/user-1"):
            payload = json.loads(request.content)
            assert payload["firstName"] == "Пётр"
            assert payload["lastName"] == "Петров"
            assert payload["requiredActions"] == ["VERIFY_EMAIL", "UPDATE_PASSWORD"]
            return httpx.Response(204)
        if path.endswith("/admin/realms/aios/roles/sales"):
            return httpx.Response(200, json={"id": "role-1", "name": "sales"})
        if path.endswith("/role-mappings/realm"):
            return httpx.Response(204)
        if path.endswith("/execute-actions-email"):
            return httpx.Response(204)
        return httpx.Response(404)

    settings = SimpleNamespace(
        keycloak_admin_base_url="http://keycloak:8080",
        keycloak_admin_realm="aios",
        keycloak_admin_client_id="crm-inviter",
        keycloak_admin_client_secret="not-logged",
        keycloak_invite_client_id="aios-backend",
        keycloak_invite_redirect_uri="https://erp.example.by/crm/deals",
        keycloak_invite_lifespan_seconds=43_200,
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await KeycloakAdminClient(settings, client=http).invite_user(
            username="petrov",
            full_name="Петров Пётр",
            email="petrov@example.by",
            department="Продажи",
            role="sales",
        )

    assert result.reused is True
    assert [request.method for request in seen] == [
        "POST",
        "POST",
        "GET",
        "PUT",
        "GET",
        "POST",
        "PUT",
    ]
