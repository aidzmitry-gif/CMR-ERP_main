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
from core.services.keycloak_admin import (
    KeycloakAdminClient,
    KeycloakAdminError,
    KeycloakRoleChange,
    KeycloakUserAccess,
)
from modules.hr.models import Employee


class FakeCrmIdentityGateway:
    def __init__(self, *, fail_change: bool = False) -> None:
        self.calls: list[dict] = []
        self.fail_change = fail_change
        self.effective_roles: tuple[str, ...] | None = None
        self.access_calls: list[dict] = []
        self.fail_access = False

    async def set_user_enabled(self, **kwargs) -> KeycloakUserAccess:
        self.access_calls.append(kwargs)
        if self.fail_access:
            raise KeycloakAdminError("keycloak_access_change_transport_failed")
        return KeycloakUserAccess(
            user_id=kwargs["user_id"], enabled=kwargs["enabled"], role=kwargs["expected_role"]
        )

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

    created = await api.post(
        "/system/users/crm-staff", json={"full_name": "Иванов Иван", "position": "Менеджер"}
    )
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


async def _active_sales_user(
    session, *, role: str = "sales", suffix: str = ""
) -> tuple[Employee, User]:
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
async def test_suspend_restore_is_audited_idempotent_and_preserves_role(session, crm_staff_api):
    from core.services.auth import GUEST, CurrentUser, resolve_effective_oidc_user

    api, gateway = crm_staff_api
    employee, user = await _active_sales_user(session)
    claimed = CurrentUser(user.username, ["sales"], user.keycloak_user_id)
    path = f"/system/users/{employee.id}/crm-access"
    payload = {"enabled": False, "expected_current_status": "active"}
    headers = {"Idempotency-Key": "crm-suspend-test-001"}
    suspended = await api.post(path, headers=headers, json=payload)
    assert suspended.status_code == 200, suspended.text
    assert suspended.json()["status"] == "suspended"
    assert (await resolve_effective_oidc_user(claimed, session)).roles == [GUEST]
    repeated = await api.post(path, headers=headers, json=payload)
    assert repeated.json() == suspended.json()
    assert len(gateway.access_calls) == 1
    wrong = await api.post(
        path, headers=headers, json={"enabled": True, "expected_current_status": "suspended"}
    )
    assert wrong.status_code == 409
    restored = await api.post(
        path,
        headers={"Idempotency-Key": "crm-restore-test-001"},
        json={"enabled": True, "expected_current_status": "suspended"},
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["status"] == "active"
    # Re-enabling the same role must not revive the pre-suspension JWT.
    assert (await resolve_effective_oidc_user(claimed, session)).roles == [GUEST]
    assert user.role == "sales"
    assert [call["enabled"] for call in gateway.access_calls] == [False, True]
    events = (
        (
            await session.execute(
                select(AuditLog).where(AuditLog.action == "identity.user.crm_access_changed")
            )
        )
        .scalars()
        .all()
    )
    assert len(events) == 2
    assert all(event.actor == "director" for event in events)


@pytest.mark.asyncio
async def test_access_failure_blocks_old_jwt_and_all_automatic_retries(session, crm_staff_api):
    from core.services.auth import GUEST, CurrentUser, resolve_effective_oidc_user

    api, gateway = crm_staff_api
    employee, user = await _active_sales_user(session)
    gateway.fail_access = True
    path = f"/system/users/{employee.id}/crm-access"
    body = {"enabled": False, "expected_current_status": "active"}
    first = await api.post(path, headers={"Idempotency-Key": "crm-access-failure-001"}, json=body)
    assert first.status_code == 502
    assert first.json()["detail"] == "identity_access_reconciliation_required"
    assert (
        await resolve_effective_oidc_user(
            CurrentUser(user.username, ["sales"], user.keycloak_user_id), session
        )
    ).roles == [GUEST]
    for key in ["crm-access-failure-001", "crm-access-new-key-002"]:
        assert (
            await api.post(path, headers={"Idempotency-Key": key}, json=body)
        ).status_code == 409
    assert len(gateway.access_calls) == 1
    assert user.status == "access_change_failed"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "roles",
    ["hr", "crm_invitation_operator", "sales_head", "sales", "identity_provisioner", "onboarding"],
)
async def test_access_management_denies_non_owner_roles(session, crm_staff_api, roles):
    api, gateway = crm_staff_api
    employee, _ = await _active_sales_user(session)
    result = await api.post(
        f"/system/users/{employee.id}/crm-access",
        headers={"X-User-Roles": roles, "Idempotency-Key": "crm-access-denied-001"},
        json={"enabled": False, "expected_current_status": "active"},
    )
    assert result.status_code == 403
    assert gateway.access_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("target", ["director", "self", "foreign"])
async def test_access_management_never_changes_owner_self_or_foreign_employee(
    session, crm_staff_api, target
):
    api, gateway = crm_staff_api
    employee, user = await _active_sales_user(session)
    if target == "director":
        user.role = "director"
    elif target == "self":
        user.username = "director"
    else:
        user.department = "Финансы / офис"
    await session.commit()
    result = await api.post(
        f"/system/users/{employee.id}/crm-access",
        headers={"Idempotency-Key": "crm-protected-target-001"},
        json={"enabled": False, "expected_current_status": "active"},
    )
    assert result.status_code == 403
    assert gateway.access_calls == []


@pytest.mark.asyncio
async def test_gateway_access_updates_only_enabled_and_denies_privileged_role_drift():
    enabled = True
    calls = []
    roles = ["sales", "offline_access"]

    def handle(request):
        nonlocal enabled
        import json

        calls.append((request.method, request.url.path))
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "synthetic-test"})
        if request.url.path.endswith("/composite"):
            return httpx.Response(200, json=[{"name": role} for role in roles])
        if request.url.path.endswith("/logout"):
            return httpx.Response(204)
        if request.method == "PUT":
            body = json.loads(request.content)
            assert set(body) == {"enabled"}
            enabled = body["enabled"]
            return httpx.Response(204)
        return httpx.Response(200, json={"id": "kc-test", "enabled": enabled})

    settings = SimpleNamespace(
        keycloak_admin_base_url="https://identity.example.invalid",
        keycloak_admin_realm="test",
        keycloak_admin_client_id="gateway",
        keycloak_admin_client_secret="synthetic-test",
        keycloak_invite_client_id="erp",
        keycloak_invite_redirect_uri="https://erp.example.invalid",
        keycloak_invite_lifespan_seconds=600,
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        gateway = KeycloakAdminClient(settings, client=client)
        assert (
            await gateway.set_user_enabled(user_id="kc-test", enabled=False, expected_role="sales")
        ).enabled is False
        assert (
            await gateway.set_user_enabled(user_id="kc-test", enabled=True, expected_role="sales")
        ).enabled is True
        puts = sum(method == "PUT" for method, _ in calls)
        roles.append("director")
        with pytest.raises(KeycloakAdminError):
            await gateway.set_user_enabled(user_id="kc-test", enabled=False, expected_role="sales")
        assert sum(method == "PUT" for method, _ in calls) == puts
    assert sum(path.endswith("/logout") for _, path in calls) == 2


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
    assert gateway.calls == [
        {"user_id": "kc-crm-manager", "current_role": "sales", "target_role": "sales_head"}
    ]
    user = (await session.execute(select(User).where(User.employee_id == employee.id))).scalar_one()
    assert user.role == "sales_head"
    audit = (
        await session.execute(
            select(AuditLog).where(AuditLog.action == "identity.user.crm_role_changed")
        )
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
        await session.execute(
            select(AuditLog).where(AuditLog.action == "identity.user.crm_role_change_failed")
        )
    ).scalar_one()
    assert failed_audit.detail["requires_reconciliation"] is True


@pytest.mark.asyncio
async def test_crm_role_change_rejects_prior_uncertain_operation_and_inactive_hr(
    session, crm_staff_api
):
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
async def test_crm_role_change_fails_closed_for_unsafe_gateway_effective_roles(
    session, crm_staff_api
):
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
@pytest.mark.parametrize("default_role,expected_status", [
    ("default-roles-crm-test", 200), ("default-roles-aios", 409),
    ("default-roles-unrelated", 409), ("director", 409),
])
async def test_role_change_uses_exact_configured_realm_default(
    session, crm_staff_api, monkeypatch, default_role, expected_status,
):
    monkeypatch.setattr("core.runtime.identity_routes.get_settings",
                        lambda: SimpleNamespace(keycloak_admin_realm="crm-test"))
    api, gateway = crm_staff_api
    employee, _ = await _active_sales_user(session)
    gateway.effective_roles = ("sales_head", default_role, "offline_access", "uma_authorization")
    response = await api.post(f"/system/users/{employee.id}/crm-role",
        headers={"Idempotency-Key": "configured-realm-role-test"},
        json={"role": "sales_head", "expected_current_role": "sales"})
    assert response.status_code == expected_status


@pytest.mark.asyncio
async def test_confirmed_reconciliation_supersedes_old_failure_without_deleting_audit(session, crm_staff_api):
    api, gateway = crm_staff_api
    employee, _ = await _active_sales_user(session)
    request = AuditLog(actor="director", action="identity.user.crm_role_change_requested",
        entity_ref=f"employee:{employee.id}", detail={"idempotency_key": "old-uncertain-request",
            "expected_current_role": "sales_head", "target_role": "sales"})
    session.add(request)
    await session.flush()
    session.add(AuditLog(actor="director", action="identity.user.crm_role_change_failed",
        entity_ref=f"employee:{employee.id}", detail={"request_id": request.id, "error_code": "transport_failed"}))
    await session.flush()
    session.add(AuditLog(actor="director", action="identity.user.crm_role_changed",
        entity_ref=f"employee:{employee.id}", detail={"request_id": request.id, "role": "sales",
            "previous_role": "sales_head", "manual_reconciliation": True}))
    await session.commit()
    response = await api.post(f"/system/users/{employee.id}/crm-role",
        headers={"Idempotency-Key": "after-confirmed-reconciliation"},
        json={"role": "sales_head", "expected_current_role": "sales"})
    assert response.status_code == 200
    assert len(gateway.calls) == 1
    failures = (await session.execute(select(AuditLog).where(
        AuditLog.action == "identity.user.crm_role_change_failed"))).scalars().all()
    assert len(failures) == 1


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
                else [
                    {"id": "head", "name": "sales_head"},
                    {"id": "offline", "name": "offline_access"},
                ]
            )
            return httpx.Response(200, json=roles)
        if path.endswith("/users/kc-crm-manager/role-mappings/realm/composite"):
            return httpx.Response(
                200,
                json=[
                    {"id": "head", "name": "sales_head"},
                    {"id": "offline", "name": "offline_access"},
                ],
            )
        if path.endswith("/roles/sales_head"):
            return httpx.Response(200, json={"id": "head", "name": "sales_head"})
        if path.endswith("/users/kc-crm-manager/role-mappings/realm") and request.method in {
            "POST",
            "DELETE",
        }:
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
