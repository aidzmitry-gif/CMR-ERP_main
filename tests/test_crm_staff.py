"""Контракт безопасного оператораского реестра CRM и смены CRM-ролей."""

from __future__ import annotations

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
from core.services.keycloak_admin import KeycloakAdminClient, KeycloakAdminError, KeycloakRoleChange
from modules.hr.models import Employee


class FakeCrmIdentityGateway:
    def __init__(self, *, fail_change: bool = False) -> None:
        self.calls: list[dict] = []
        self.fail_change = fail_change
        self.effective_roles: tuple[str, ...] | None = None

    async def change_crm_role(self, **kwargs) -> KeycloakRoleChange:
        self.calls.append(kwargs)
        if self.fail_change:
            raise KeycloakAdminError("keycloak_crm_role_change_transport_failed")
        return KeycloakRoleChange(
            user_id=kwargs["user_id"],
            role=kwargs["target_role"],
            effective_roles=self.effective_roles or (kwargs["target_role"], "offline_access"),
        )


@pytest_asyncio.fixture
async def crm_staff_api(session):
    app = create_app()
    gateway = FakeCrmIdentityGateway()

    async def _session():
        yield session

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_identity_gateway] = lambda: gateway
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-User": "director", "X-User-Roles": "director"},
    ) as client:
        yield client, gateway


@pytest.mark.asyncio
async def test_crm_staff_create_list_and_duplicate_are_sales_only(session, crm_staff_api):
    api, _ = crm_staff_api
    foreign = Employee(full_name="Финансист", department="Финансы / офис", status="active")
    session.add(foreign)
    await session.commit()

    created = await api.post("/system/users/crm-staff", json={"full_name": "Иванов Иван", "position": "Менеджер"})
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["created"] is True
    assert body["department"] == "Продажи"
    assert body["email"] is None and body["role"] is None
    assert [role["slug"] for role in body["allowed_roles"]] == ["sales_head", "sales", "sales_cli"]

    duplicate = await api.post("/system/users/crm-staff", json={"full_name": "Иванов Иван"})
    assert duplicate.status_code == 201
    assert duplicate.json()["created"] is False
    assert duplicate.json()["employee_id"] == body["employee_id"]

    listed = await api.get("/system/users/crm-staff")
    assert listed.status_code == 200
    assert [row["full_name"] for row in listed.json()] == ["Иванов Иван"]


@pytest.mark.asyncio
async def test_crm_staff_rejects_non_super_and_onboarding(session, crm_staff_api):
    api, _ = crm_staff_api
    employee = Employee(full_name="Сотрудник", department="Продажи", status="active")
    session.add(employee)
    await session.commit()

    denied = await api.get("/system/users/crm-staff", headers={"X-User-Roles": "sales"})
    assert denied.status_code == 403
    onboarding = await api.post(
        "/system/users/crm-staff",
        headers={"X-User-Roles": "onboarding"},
        json={"full_name": "Нельзя"},
    )
    assert onboarding.status_code == 403


async def _active_sales_user(session, *, role: str = "sales", suffix: str = "") -> tuple[Employee, User]:
    employee = Employee(full_name=f"Менеджер CRM{suffix}", department="Продажи", status="active")
    session.add(employee)
    await session.flush()
    user = User(
        username=f"crm-manager{suffix}",
        full_name=employee.full_name,
        email=f"crm-manager{suffix}@example.by",
        employee_id=employee.id,
        department="Продажи",
        role=role,
        keycloak_user_id=f"kc-crm-manager{suffix}",
        status="active",
    )
    session.add(user)
    await session.commit()
    return employee, user


@pytest.mark.asyncio
async def test_crm_role_change_is_idempotent_and_audited(session, crm_staff_api):
    api, gateway = crm_staff_api
    employee, _ = await _active_sales_user(session)
    key = "crm-role-change-0001"

    response = await api.post(
        f"/system/users/{employee.id}/crm-role",
        headers={"Idempotency-Key": key},
        json={"role": "sales_head", "expected_current_role": "sales"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["role"] == "sales_head"
    assert gateway.calls == [{"user_id": "kc-crm-manager", "current_role": "sales", "target_role": "sales_head"}]
    user = (await session.execute(select(User).where(User.employee_id == employee.id))).scalar_one()
    assert user.role == "sales_head"
    audit = (
        await session.execute(select(AuditLog).where(AuditLog.action == "identity.user.crm_role_changed"))
    ).scalar_one()
    assert audit.detail["previous_role"] == "sales" and audit.detail["sessions_revoked"] is True

    replay = await api.post(
        f"/system/users/{employee.id}/crm-role",
        headers={"Idempotency-Key": key},
        json={"role": "sales_head", "expected_current_role": "sales"},
    )
    assert replay.status_code == 200
    assert len(gateway.calls) == 1


@pytest.mark.asyncio
async def test_crm_role_change_rejects_tamper_and_upstream_failure(session, crm_staff_api):
    api, gateway = crm_staff_api
    employee, _ = await _active_sales_user(session)
    tamper = await api.post(
        f"/system/users/{employee.id}/crm-role",
        headers={"Idempotency-Key": "crm-role-tamper-0001"},
        json={"role": "director", "expected_current_role": "sales"},
    )
    assert tamper.status_code == 422
    stale = await api.post(
        f"/system/users/{employee.id}/crm-role",
        headers={"Idempotency-Key": "crm-role-stale-00001"},
        json={"role": "sales_head", "expected_current_role": "sales_cli"},
    )
    assert stale.status_code == 409
    assert gateway.calls == []

    gateway.fail_change = True
    failed = await api.post(
        f"/system/users/{employee.id}/crm-role",
        headers={"Idempotency-Key": "crm-role-failure-001"},
        json={"role": "sales_cli", "expected_current_role": "sales"},
    )
    assert failed.status_code == 502
    user = (await session.execute(select(User).where(User.employee_id == employee.id))).scalar_one()
    assert user.role == "sales" and user.status == "role_change_failed"
    failed_audit = (
        await session.execute(select(AuditLog).where(AuditLog.action == "identity.user.crm_role_change_failed"))
    ).scalar_one()
    assert failed_audit.detail["requires_reconciliation"] is True


@pytest.mark.asyncio
async def test_crm_role_change_rejects_prior_uncertain_operation_and_inactive_hr(session, crm_staff_api):
    api, gateway = crm_staff_api
    employee, user = await _active_sales_user(session)
    session.add(
        AuditLog(
            actor="director",
            action="identity.user.crm_role_change_requested",
            entity_ref=f"employee:{employee.id}",
            detail={
                "idempotency_key": "prior-uncertain-001",
                "target_role": "sales_cli",
                "expected_current_role": "sales",
                "status": "sending",
            },
        )
    )
    await session.commit()
    blocked = await api.post(
        f"/system/users/{employee.id}/crm-role",
        headers={"Idempotency-Key": "new-role-change-0001"},
        json={"role": "sales_head", "expected_current_role": "sales"},
    )
    assert blocked.status_code == 409 and gateway.calls == []

    inactive_employee, _ = await _active_sales_user(session, suffix="-inactive")
    inactive_employee.status = "dismissed"
    await session.commit()
    inactive = await api.post(
        f"/system/users/{inactive_employee.id}/crm-role",
        headers={"Idempotency-Key": "inactive-role-change-01"},
        json={"role": "sales_head", "expected_current_role": "sales"},
    )
    assert inactive.status_code == 409 and gateway.calls == []


@pytest.mark.asyncio
async def test_crm_role_change_fails_closed_for_unsafe_gateway_effective_roles(session, crm_staff_api):
    api, gateway = crm_staff_api
    employee, _ = await _active_sales_user(session)
    gateway.effective_roles = ("sales_head", "director")
    response = await api.post(
        f"/system/users/{employee.id}/crm-role",
        headers={"Idempotency-Key": "unsafe-effective-role"},
        json={"role": "sales_head", "expected_current_role": "sales"},
    )
    assert response.status_code == 409
    user = (await session.execute(select(User).where(User.employee_id == employee.id))).scalar_one()
    assert user.role == "sales" and user.status == "role_change_failed"


@pytest.mark.asyncio
async def test_crm_visibility_change_is_separate_optimistic_and_idempotent(session, crm_staff_api):
    api, _ = crm_staff_api
    employee, _ = await _active_sales_user(session)
    key = "crm-visibility-00001"
    changed = await api.post(
        f"/system/users/{employee.id}/crm-visibility",
        headers={"Idempotency-Key": key},
        json={"deal_visibility": "own", "expected_current_visibility": "all"},
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["deal_visibility"] == "own"
    user = (await session.execute(select(User).where(User.employee_id == employee.id))).scalar_one()
    assert user.deal_visibility == "own"

    replay = await api.post(
        f"/system/users/{employee.id}/crm-visibility",
        headers={"Idempotency-Key": key},
        json={"deal_visibility": "own", "expected_current_visibility": "all"},
    )
    assert replay.status_code == 200
    stale = await api.post(
        f"/system/users/{employee.id}/crm-visibility",
        headers={"Idempotency-Key": "crm-visibility-stale"},
        json={"deal_visibility": "all", "expected_current_visibility": "all"},
    )
    assert stale.status_code == 409


@pytest.mark.asyncio
async def test_keycloak_crm_role_change_preserves_unrelated_roles_and_revokes_sessions():
    seen: list[httpx.Request] = []
    mappings_reads = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal mappings_reads
        seen.append(request)
        path = request.url.path
        if path.endswith("/protocol/openid-connect/token"):
            return httpx.Response(200, json={"access_token": "service-token"})
        if path.endswith("/users/kc-crm-manager/role-mappings/realm") and request.method == "GET":
            mappings_reads += 1
            roles = (
                [{"id": "sales", "name": "sales"}, {"id": "offline", "name": "offline_access"}]
                if mappings_reads == 1
                else [{"id": "head", "name": "sales_head"}, {"id": "offline", "name": "offline_access"}]
            )
            return httpx.Response(200, json=roles)
        if path.endswith("/users/kc-crm-manager/role-mappings/realm/composite"):
            return httpx.Response(
                200,
                json=[{"id": "head", "name": "sales_head"}, {"id": "offline", "name": "offline_access"}],
            )
        if path.endswith("/roles/sales_head"):
            return httpx.Response(200, json={"id": "head", "name": "sales_head"})
        if path.endswith("/users/kc-crm-manager/role-mappings/realm") and request.method in {"POST", "DELETE"}:
            return httpx.Response(204)
        if path.endswith("/users/kc-crm-manager/logout"):
            return httpx.Response(204)
        return httpx.Response(404)

    settings = SimpleNamespace(
        keycloak_admin_base_url="http://keycloak:8080",
        keycloak_admin_realm="aios",
        keycloak_admin_client_id="crm-inviter",
        keycloak_admin_client_secret="not-logged",
        keycloak_invite_client_id="aios-backend",
        keycloak_invite_redirect_uri="https://erp.example.by/",
        keycloak_invite_lifespan_seconds=43_200,
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await KeycloakAdminClient(settings, client=http).change_crm_role(
            user_id="kc-crm-manager", current_role="sales", target_role="sales_head"
        )

    assert result.role == "sales_head"
    assert result.effective_roles == ("offline_access", "sales_head")
    # POST target, DELETE only old sales mapping, read-back, then logout.
    assert [(request.method, request.url.path.rsplit("/", 1)[-1]) for request in seen] == [
        ("POST", "token"),
        ("GET", "realm"),
        ("GET", "sales_head"),
        ("POST", "realm"),
        ("DELETE", "realm"),
        ("GET", "realm"),
        ("GET", "composite"),
        ("POST", "logout"),
    ]
