"""Приглашение сотрудника: HR-связь, department-role gate и Keycloak Admin API."""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from config.access import is_package_allowed
from core.domain.models import (
    AuditLog,
    IdentityAccessActivationRequest,
    IdentityInvitationRequest,
    User,
)
from core.runtime.app import create_app
from core.runtime.deps import get_session
from core.runtime.identity_routes import get_identity_gateway
from core.services.auth import CurrentUser, has_permission
from core.services.keycloak_admin import (
    KeycloakActivation,
    KeycloakAdminClient,
    KeycloakAdminConflict,
    KeycloakAdminError,
    KeycloakInvitation,
)
from modules.hr.models import Employee


class FakeIdentityGateway:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.activation_stage_calls: list[dict] = []
        self.onboarding_removal_calls: list[dict] = []

    async def invite_user(self, **kwargs) -> KeycloakInvitation:
        self.calls.append(kwargs)
        return KeycloakInvitation(
            user_id="kc-user-42",
            username=kwargs["username"],
            email=kwargs["email"],
            role="onboarding",
            actions=("VERIFY_EMAIL", "UPDATE_PASSWORD"),
            reused=False,
        )

    async def stage_activation_target(self, **kwargs) -> KeycloakActivation:
        self.activation_stage_calls.append(kwargs)
        return KeycloakActivation(user_id=kwargs["user_id"], role=kwargs["expected_role"])

    async def remove_onboarding_role(self, **kwargs) -> None:
        self.onboarding_removal_calls.append(kwargs)


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
    employee = Employee(full_name="Петров Пётр", position="Менеджер", department="Продажи")
    session.add(employee)
    await session.commit()
    await session.refresh(employee)

    response = await api.post(
        "/system/users/invite",
        headers={"Idempotency-Key": "invite-petr-001"},
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
    assert body["department"] is None and body["role"] == "onboarding"
    assert body["expected_department"] == "Продажи" and body["expected_role"] == "sales"
    assert body["keycloak_user_id"] == "kc-user-42" and body["status"] == "onboarding"
    assert gateway.calls == [
        {
            "username": "petr",
            "full_name": "Петров Пётр",
            "email": "petr@example.by",
            "expected_department": "Продажи",
            "expected_role": "sales",
        }
    ]

    user = (await session.execute(select(User).where(User.employee_id == employee.id))).scalar_one()
    audit = (
        await session.execute(select(AuditLog).where(AuditLog.action == "identity.user.invited"))
    ).scalar_one()
    await session.refresh(employee)
    assert user.email == "petr@example.by" and employee.department == "Продажи"
    assert user.role == "onboarding" and user.department is None
    assert user.expected_department == "Продажи" and user.expected_role == "sales"
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
        headers={"Idempotency-Key": "invite-wrong-role-001"},
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
async def test_invite_derives_department_from_hr_and_never_changes_it(session, identity_api):
    api, gateway = identity_api
    employee = Employee(full_name="Сотрудник", department="Продажи")
    session.add(employee)
    await session.commit()
    await session.refresh(employee)

    response = await api.post(
        "/system/users/invite",
        headers={"Idempotency-Key": "invite-department-mismatch-001"},
        json={
            "employee_id": employee.id,
            "email": "user@example.by",
            "department": "Финансы",
            "role": "finance",
        },
    )

    assert response.status_code == 422
    assert gateway.calls == []
    await session.refresh(employee)
    assert employee.department == "Продажи"


@pytest.mark.asyncio
async def test_preflight_requires_department_to_be_set_in_hr(session, identity_api):
    api, gateway = identity_api
    employee = Employee(full_name="Сотрудник", department="")
    session.add(employee)
    await session.commit()
    await session.refresh(employee)

    response = await api.post(
        "/system/users/preflight",
        json={
            "employee_id": employee.id,
            "email": "user@example.by",
            "department": "Продажи",
            "role": "sales",
        },
    )

    assert response.status_code == 422
    assert gateway.calls == []


@pytest.mark.asyncio
async def test_invitation_preflight_and_send_reject_inactive_hr_employee(session, identity_api):
    api, gateway = identity_api
    employee = Employee(full_name="Уволенный сотрудник", department="Продажи", status="dismissed")
    session.add(employee)
    await session.commit()
    await session.refresh(employee)
    payload = {
        "employee_id": employee.id,
        "email": "dismissed@example.by",
        "department": "Продажи",
        "role": "sales",
    }

    preflight = await api.post("/system/users/preflight", json=payload)
    invite = await api.post(
        "/system/users/invite",
        headers={"Idempotency-Key": "invite-dismissed-employee-001"},
        json=payload,
    )
    assert preflight.status_code == 409
    assert invite.status_code == 409
    assert gateway.calls == []


@pytest.mark.asyncio
async def test_invitations_list_excludes_legacy_active_users_with_no_expected_access(
    session, identity_api
):
    api, _ = identity_api
    session.add(
        User(
            username="legacy-active",
            full_name="Старый пользователь",
            email="legacy.active@example.by",
            employee_id=900_001,
            department="Продажи",
            role="sales",
            status="active",
        )
    )
    await session.commit()

    response = await api.get("/system/users/invitations")
    assert response.status_code == 200, response.text
    assert response.json() == []


@pytest.mark.asyncio
async def test_invitation_operations_requires_read_permission(session, identity_api):
    api, _ = identity_api

    response = await api.get(
        "/system/users/invitation-operations", headers={"X-User-Roles": "sales"}
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_invitation_operations_exposes_failed_request_without_technical_or_unrelated_pii(
    session, identity_api
):
    api, _ = identity_api
    employee = Employee(full_name="Видимый сотрудник", department="Продажи")
    unrelated = Employee(full_name="Чужой сотрудник", department="Продажи")
    session.add_all([employee, unrelated])
    await session.commit()
    await session.refresh(employee)
    await session.refresh(unrelated)
    session.add(
        IdentityInvitationRequest(
            idempotency_key="private-idempotency-key-0001",
            employee_id=employee.id,
            username="visible.employee",
            email="visible.employee@example.by",
            department="Продажи",
            role="sales",
            actor="hidden-operator",
            status="failed",
            keycloak_user_id="keycloak-secret-id",
            error_code="keycloak_invite_email_failed",
        )
    )
    await session.commit()

    response = await api.get("/system/users/invitation-operations")

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body) == 1
    assert body[0] == {
        "operation_kind": "invite",
        "request_id": body[0]["request_id"],
        "employee_id": employee.id,
        "full_name": "Видимый сотрудник",
        "email": "visible.employee@example.by",
        "username": "visible.employee",
        "target_department": "Продажи",
        "target_role": "sales",
        "status": "failed",
        "error_code": "keycloak_invite_email_failed",
        "created_at": body[0]["created_at"],
        "completed_at": None,
        "requires_reconciliation": True,
    }
    serialized = response.text
    assert "private-idempotency-key-0001" not in serialized
    assert "keycloak-secret-id" not in serialized
    assert "hidden-operator" not in serialized
    assert "Чужой сотрудник" not in serialized


@pytest.mark.asyncio
async def test_invitation_operations_marks_cleanup_pending_activation_for_reconciliation(
    session, identity_api
):
    api, _ = identity_api
    employee = Employee(full_name="Сотрудник активации", department="Продажи")
    session.add(employee)
    await session.commit()
    await session.refresh(employee)
    user = User(
        username="activation.employee",
        full_name="Сотрудник активации",
        email="activation.employee@example.by",
        employee_id=employee.id,
        department="Продажи",
        role="sales",
        expected_department="Продажи",
        expected_role="sales",
        status="active_pending_cleanup",
    )
    session.add(user)
    await session.flush()
    session.add(
        IdentityAccessActivationRequest(
            idempotency_key="activation-cleanup-pending-0001",
            user_id=user.id,
            employee_id=employee.id,
            expected_department="Продажи",
            expected_role="sales",
            actor="hidden-operator",
            status="cleanup_pending",
        )
    )
    await session.commit()

    response = await api.get("/system/users/invitation-operations")

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body) == 1
    assert body[0] == {
        "operation_kind": "activation",
        "request_id": body[0]["request_id"],
        "employee_id": employee.id,
        "full_name": "Сотрудник активации",
        "email": "activation.employee@example.by",
        "username": "activation.employee",
        "target_department": "Продажи",
        "target_role": "sales",
        "status": "cleanup_pending",
        "error_code": None,
        "created_at": body[0]["created_at"],
        "completed_at": None,
        "requires_reconciliation": True,
    }


@pytest.mark.asyncio
async def test_invite_requires_identity_permission(session, identity_api):
    api, gateway = identity_api
    employee = Employee(full_name="Сотрудник", department="Продажи")
    session.add(employee)
    await session.commit()
    await session.refresh(employee)

    response = await api.post(
        "/system/users/invite",
        headers={"X-User-Roles": "sales", "Idempotency-Key": "invite-no-access-001"},
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
async def test_existing_onboarding_user_with_new_idempotency_key_never_resends_invitation(
    session, identity_api
):
    api, gateway = identity_api
    employee = Employee(full_name="Повторный сотрудник", department="Продажи")
    session.add(employee)
    await session.commit()
    await session.refresh(employee)
    payload = {
        "employee_id": employee.id,
        "email": "repeat.employee@example.by",
        "department": "Продажи",
        "role": "sales",
    }

    first = await api.post(
        "/system/users/invite",
        headers={"Idempotency-Key": "repeat-invite-first-key-001"},
        json=payload,
    )
    second = await api.post(
        "/system/users/invite",
        headers={"Idempotency-Key": "repeat-invite-new-key-002"},
        json=payload,
    )

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert second.json() == first.json()
    assert len(gateway.calls) == 1
    requests = (
        (
            await session.execute(
                select(IdentityInvitationRequest).where(
                    IdentityInvitationRequest.employee_id == employee.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_identity_provisioner_can_prepare_and_send_but_has_no_system_or_hr_access(
    session, identity_api
):
    api, gateway = identity_api
    employee = Employee(full_name="Сервисный сотрудник", department="Продажи")
    session.add(employee)
    await session.commit()
    await session.refresh(employee)

    response = await api.post(
        "/system/users/invite",
        headers={
            "X-User": "service-account-aios-inviter",
            "X-User-Roles": "identity_provisioner",
            "Idempotency-Key": "invite-service-employee-001",
        },
        json={
            "employee_id": employee.id,
            "email": "service.employee@example.by",
            "department": "Продажи",
            "role": "sales",
        },
    )

    assert response.status_code == 201, response.text
    assert gateway.calls[0]["username"] == "service.employee"
    assert gateway.calls[0]["expected_role"] == "sales"
    core = api._transport.app.state.core
    service_user = CurrentUser("service-account-aios-inviter", ["identity_provisioner"])
    assert has_permission(core, service_user, "identity.invite.prepare") is True
    assert has_permission(core, service_user, "identity.invite.send") is True
    assert has_permission(core, service_user, "identity.invite") is False
    assert has_permission(core, service_user, "system.write") is False
    assert is_package_allowed("hr", service_user.roles) is False


@pytest.mark.asyncio
async def test_invite_preflight_normalizes_identity_without_calling_keycloak(session, identity_api):
    api, gateway = identity_api
    employee = Employee(full_name="Петров Пётр", department="Продажи")
    session.add(employee)
    await session.commit()
    await session.refresh(employee)

    response = await api.post(
        "/system/users/preflight",
        headers={
            "X-User": "service-account-aios-inviter",
            "X-User-Roles": "identity_provisioner",
        },
        json={
            "employee_id": employee.id,
            "email": " Petr.Example@Example.BY ",
            "department": "Продажи",
            "role": "sales",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "employee_id": employee.id,
        "full_name": "Петров Пётр",
        "username": "petr.example",
        "email": "petr.example@example.by",
        "department": "Продажи",
        "role": "sales",
        "ready": True,
    }
    assert gateway.calls == []


@pytest.mark.asyncio
async def test_invite_requires_idempotency_key(session, identity_api):
    api, gateway = identity_api
    employee = Employee(full_name="Сотрудник", department="Продажи")
    session.add(employee)
    await session.commit()
    await session.refresh(employee)

    response = await api.post(
        "/system/users/invite",
        json={
            "employee_id": employee.id,
            "email": "stable@example.by",
            "department": "Продажи",
            "role": "sales",
        },
    )

    assert response.status_code == 400
    assert gateway.calls == []


@pytest.mark.asyncio
async def test_invite_replay_with_same_idempotency_key_calls_gateway_once(session, identity_api):
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

    headers = {"Idempotency-Key": "stable-employee-invite-001"}
    first = await api.post("/system/users/invite", headers=headers, json=payload)
    second = await api.post("/system/users/invite", headers=headers, json=payload)

    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert first.json() == second.json()
    assert len(gateway.calls) == 1


@pytest.mark.asyncio
async def test_invite_rejects_reuse_of_idempotency_key_with_different_payload(
    session, identity_api
):
    api, gateway = identity_api
    employee = Employee(full_name="Сотрудник", department="Продажи")
    session.add(employee)
    await session.commit()
    await session.refresh(employee)
    headers = {"Idempotency-Key": "stable-employee-invite-002"}
    payload = {
        "employee_id": employee.id,
        "email": "stable@example.by",
        "department": "Продажи",
        "role": "sales",
        "username": "stable",
    }

    first = await api.post("/system/users/invite", headers=headers, json=payload)
    changed = await api.post(
        "/system/users/invite",
        headers=headers,
        json={**payload, "role": "sales_head"},
    )

    assert first.status_code == 201, first.text
    assert changed.status_code == 409
    assert len(gateway.calls) == 1


@pytest.mark.asyncio
async def test_failed_invite_is_persisted_and_never_retried_automatically(session, identity_api):
    api, _ = identity_api
    employee = Employee(full_name="Сотрудник", department="Продажи")
    session.add(employee)
    await session.commit()
    await session.refresh(employee)

    class FailingGateway:
        def __init__(self) -> None:
            self.calls = 0

        async def invite_user(self, **kwargs) -> KeycloakInvitation:
            self.calls += 1
            raise KeycloakAdminError("keycloak_invite_email_failed")

    gateway = FailingGateway()
    api._transport.app.dependency_overrides[get_identity_gateway] = lambda: gateway
    payload = {
        "employee_id": employee.id,
        "email": "stable@example.by",
        "department": "Продажи",
        "role": "sales",
    }
    headers = {"Idempotency-Key": "stable-employee-invite-failure-001"}

    first = await api.post("/system/users/invite", headers=headers, json=payload)
    second = await api.post("/system/users/invite", headers=headers, json=payload)

    assert first.status_code == 502, first.text
    assert second.status_code == 409, second.text
    assert gateway.calls == 1
    request = (
        await session.execute(
            select(IdentityInvitationRequest).where(
                IdentityInvitationRequest.employee_id == employee.id
            )
        )
    ).scalar_one()
    assert request.status == "failed" and request.error_code == "keycloak_invite_email_failed"


@pytest.mark.asyncio
async def test_activation_applies_only_persisted_expected_access_after_supervisor_action(
    session, identity_api
):
    api, gateway = identity_api
    employee = Employee(full_name="Сотрудник", department="Продажи")
    session.add(employee)
    await session.commit()
    await session.refresh(employee)
    invite = await api.post(
        "/system/users/invite",
        headers={"Idempotency-Key": "onboarding-invite-activation-001"},
        json={
            "employee_id": employee.id,
            "email": "employee@example.by",
            "department": "Продажи",
            "role": "sales",
        },
    )
    assert invite.status_code == 201, invite.text

    # Роль в теле намеренно игнорируется: endpoint берёт только expected_* из БД.
    activated = await api.post(
        f"/system/users/{employee.id}/activate",
        headers={"Idempotency-Key": "onboarding-activate-employee-001"},
        json={"role": "director", "department": "Руководство"},
    )
    assert activated.status_code == 200, activated.text
    assert activated.json() == {
        "id": invite.json()["id"],
        "employee_id": employee.id,
        "username": "employee",
        "department": "Продажи",
        "role": "sales",
        "status": "active",
    }
    assert gateway.activation_stage_calls == [{"user_id": "kc-user-42", "expected_role": "sales"}]
    assert gateway.onboarding_removal_calls == [{"user_id": "kc-user-42"}]
    user = (await session.execute(select(User).where(User.employee_id == employee.id))).scalar_one()
    assert user.status == "active"
    assert user.department == "Продажи" and user.role == "sales"
    assert user.expected_department is None and user.expected_role is None
    audit = (
        await session.execute(
            select(AuditLog).where(AuditLog.action == "identity.user.activation_target_assigned")
        )
    ).scalar_one()
    assert audit.detail["role"] == "sales" and audit.actor == "owner"
    completed_audit = (
        await session.execute(select(AuditLog).where(AuditLog.action == "identity.user.activated"))
    ).scalar_one()
    assert completed_audit.actor == "owner"

    replay = await api.post(
        f"/system/users/{employee.id}/activate",
        headers={"Idempotency-Key": "onboarding-activate-employee-001"},
    )
    assert replay.status_code == 200 and replay.json() == activated.json()
    assert len(gateway.activation_stage_calls) == 1
    assert len(gateway.onboarding_removal_calls) == 1


@pytest.mark.asyncio
async def test_activation_commit_failure_keeps_onboarding_role_and_requires_reconciliation(
    session, identity_api, monkeypatch
):
    api, gateway = identity_api
    employee = Employee(full_name="Сотрудник", department="Продажи")
    session.add(employee)
    await session.commit()
    await session.refresh(employee)
    invited = await api.post(
        "/system/users/invite",
        headers={"Idempotency-Key": "onboarding-invite-commit-failure-001"},
        json={
            "employee_id": employee.id,
            "email": "employee.commit.failure@example.by",
            "department": "Продажи",
            "role": "sales",
        },
    )
    assert invited.status_code == 201, invited.text
    employee_id = employee.id

    real_commit = session.commit
    commit_count = 0

    async def fail_pending_cleanup_commit():
        nonlocal commit_count
        commit_count += 1
        if commit_count == 2:
            raise RuntimeError("local persistence failed")
        await real_commit()

    monkeypatch.setattr(session, "commit", fail_pending_cleanup_commit)
    response = await api.post(
        f"/system/users/{employee_id}/activate",
        headers={"Idempotency-Key": "onboarding-activate-commit-failure-001"},
    )
    assert response.status_code == 502
    assert response.json()["detail"] == "identity_activation_reconciliation_required"
    assert gateway.activation_stage_calls == [{"user_id": "kc-user-42", "expected_role": "sales"}]
    assert gateway.onboarding_removal_calls == []
    user = (await session.execute(select(User).where(User.employee_id == employee_id))).scalar_one()
    assert user.status == "onboarding" and user.role == "onboarding"
    activation = (
        await session.execute(
            select(IdentityAccessActivationRequest).where(
                IdentityAccessActivationRequest.employee_id == employee_id
            )
        )
    ).scalar_one()
    assert activation.status == "sending"


@pytest.mark.asyncio
async def test_activation_is_supervisor_only_and_keycloak_failure_stays_onboarding(
    session, identity_api
):
    api, gateway = identity_api
    employee = Employee(full_name="Сотрудник", department="Продажи")
    session.add(employee)
    await session.commit()
    await session.refresh(employee)
    invite = await api.post(
        "/system/users/invite",
        headers={"Idempotency-Key": "onboarding-invite-failure-001"},
        json={
            "employee_id": employee.id,
            "email": "employee.failure@example.by",
            "department": "Продажи",
            "role": "sales",
        },
    )
    assert invite.status_code == 201, invite.text

    forbidden = await api.post(
        f"/system/users/{employee.id}/activate",
        headers={"X-User-Roles": "sales", "Idempotency-Key": "onboarding-activate-no-right-001"},
    )
    assert forbidden.status_code == 403
    assert gateway.activation_stage_calls == []

    class FailingActivationGateway(FakeIdentityGateway):
        async def stage_activation_target(self, **kwargs) -> KeycloakActivation:
            self.activation_stage_calls.append(kwargs)
            raise KeycloakAdminError("keycloak_activation_reconciliation_required")

    failing = FailingActivationGateway()
    api._transport.app.dependency_overrides[get_identity_gateway] = lambda: failing
    headers = {"Idempotency-Key": "onboarding-activate-failure-001"}
    first = await api.post(f"/system/users/{employee.id}/activate", headers=headers)
    second = await api.post(f"/system/users/{employee.id}/activate", headers=headers)
    assert first.status_code == 502 and second.status_code == 409
    assert len(failing.activation_stage_calls) == 1
    assert failing.onboarding_removal_calls == []
    user = (await session.execute(select(User).where(User.employee_id == employee.id))).scalar_one()
    assert user.status == "onboarding" and user.role == "onboarding"
    assert user.expected_department == "Продажи" and user.expected_role == "sales"


@pytest.mark.asyncio
async def test_activation_role_cleanup_error_keeps_fail_closed_state_for_reconciliation(
    session, identity_api
):
    api, _ = identity_api
    employee = Employee(full_name="Сотрудник cleanup", department="Продажи")
    session.add(employee)
    await session.commit()
    await session.refresh(employee)
    invited = await api.post(
        "/system/users/invite",
        headers={"Idempotency-Key": "cleanup-error-invite-001"},
        json={
            "employee_id": employee.id,
            "email": "cleanup.error@example.by",
            "department": "Продажи",
            "role": "sales",
        },
    )
    assert invited.status_code == 201, invited.text

    class FailingCleanupGateway(FakeIdentityGateway):
        async def remove_onboarding_role(self, **kwargs) -> None:
            self.onboarding_removal_calls.append(kwargs)
            raise KeycloakAdminError("keycloak_onboarding_cleanup_failed")

    failing = FailingCleanupGateway()
    api._transport.app.dependency_overrides[get_identity_gateway] = lambda: failing
    response = await api.post(
        f"/system/users/{employee.id}/activate",
        headers={"Idempotency-Key": "cleanup-error-activation-001"},
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "keycloak_onboarding_cleanup_failed"
    assert failing.activation_stage_calls == [{"user_id": "kc-user-42", "expected_role": "sales"}]
    assert failing.onboarding_removal_calls == [{"user_id": "kc-user-42"}]
    user = (await session.execute(select(User).where(User.employee_id == employee.id))).scalar_one()
    assert user.status == "active_pending_cleanup"
    assert user.department == "Продажи" and user.role == "sales"
    assert user.expected_department == "Продажи" and user.expected_role == "sales"
    activation = (
        await session.execute(
            select(IdentityAccessActivationRequest).where(
                IdentityAccessActivationRequest.employee_id == employee.id
            )
        )
    ).scalar_one()
    assert activation.status == "failed"
    assert activation.error_code == "keycloak_onboarding_cleanup_failed"


@pytest.mark.asyncio
async def test_activation_rechecks_hr_employee_is_active(session, identity_api):
    api, gateway = identity_api
    employee = Employee(full_name="Сотрудник", department="Продажи")
    session.add(employee)
    await session.commit()
    await session.refresh(employee)
    invite = await api.post(
        "/system/users/invite",
        headers={"Idempotency-Key": "onboarding-invite-inactive-activation-001"},
        json={
            "employee_id": employee.id,
            "email": "employee.inactive.activation@example.by",
            "department": "Продажи",
            "role": "sales",
        },
    )
    assert invite.status_code == 201, invite.text
    employee.status = "dismissed"
    await session.commit()

    response = await api.post(
        f"/system/users/{employee.id}/activate",
        headers={"Idempotency-Key": "onboarding-activate-inactive-employee-001"},
    )
    assert response.status_code == 409
    assert gateway.activation_stage_calls == []


@pytest.mark.asyncio
async def test_activation_rechecks_hr_after_target_stage_and_keeps_onboarding_on_drift(
    session, identity_api
):
    api, _ = identity_api
    employee = Employee(full_name="Сотрудник", department="Продажи")
    session.add(employee)
    await session.commit()
    await session.refresh(employee)
    employee_id = employee.id
    invite = await api.post(
        "/system/users/invite",
        headers={"Idempotency-Key": "onboarding-invite-race-check-001"},
        json={
            "employee_id": employee_id,
            "email": "employee.race@example.by",
            "department": "Продажи",
            "role": "sales",
        },
    )
    assert invite.status_code == 201, invite.text

    class HrChangesDuringStageGateway(FakeIdentityGateway):
        async def stage_activation_target(self, **kwargs) -> KeycloakActivation:
            staged = await super().stage_activation_target(**kwargs)
            # Другой оператор/транзакция меняет HR после первого durable
            # commit маршрута. Эта сессия не разделяет identity map маршрута.
            concurrent = async_sessionmaker(session.bind, expire_on_commit=False)
            async with concurrent() as other_session:
                other_employee = await other_session.get(Employee, employee_id)
                assert other_employee is not None
                other_employee.status = "dismissed"
                other_user = (
                    await other_session.execute(select(User).where(User.employee_id == employee_id))
                ).scalar_one()
                other_user.keycloak_user_id = "kc-user-manually-remapped"
                await other_session.commit()
            return staged

    changing = HrChangesDuringStageGateway()
    api._transport.app.dependency_overrides[get_identity_gateway] = lambda: changing
    response = await api.post(
        f"/system/users/{employee_id}/activate",
        headers={"Idempotency-Key": "onboarding-activate-race-check-001"},
    )
    assert response.status_code == 409
    assert changing.activation_stage_calls == [{"user_id": "kc-user-42", "expected_role": "sales"}]
    assert changing.onboarding_removal_calls == []
    user = (await session.execute(select(User).where(User.employee_id == employee_id))).scalar_one()
    assert user.status == "onboarding" and user.role == "onboarding"
    activation = (
        await session.execute(
            select(IdentityAccessActivationRequest).where(
                IdentityAccessActivationRequest.employee_id == employee_id
            )
        )
    ).scalar_one()
    assert (
        activation.status == "failed" and activation.error_code == "identity_activation_state_drift"
    )


@pytest.mark.asyncio
async def test_keycloak_client_assigns_only_onboarding_role_and_requests_one_time_actions():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        path = request.url.path
        if path.endswith("/protocol/openid-connect/token"):
            return httpx.Response(200, json={"access_token": "service-token"})
        if path.endswith("/admin/realms/aios/users") and request.method == "POST":
            payload = json.loads(request.content)
            assert payload["requiredActions"] == ["VERIFY_EMAIL", "UPDATE_PASSWORD"]
            assert payload["attributes"] == {
                "access_state": ["onboarding"],
                "expected_department": ["Продажи"],
                "expected_role": ["sales"],
            }
            assert payload["firstName"] == "Пётр"
            assert payload["lastName"] == "Петров"
            return httpx.Response(201, headers={"location": "http://kc/users/user-1"})
        if path.endswith("/admin/realms/aios/roles/onboarding"):
            return httpx.Response(200, json={"id": "role-1", "name": "onboarding"})
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
            expected_department="Продажи",
            expected_role="sales",
        )

    assert result.user_id == "user-1"
    assert result.role == "onboarding"
    assert result.actions == ("VERIFY_EMAIL", "UPDATE_PASSWORD")
    assert [request.method for request in seen] == ["POST", "POST", "GET", "POST", "PUT"]


@pytest.mark.asyncio
async def test_keycloak_activation_assigns_target_before_removing_onboarding():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        path = request.url.path
        if path.endswith("/protocol/openid-connect/token"):
            return httpx.Response(200, json={"access_token": "service-token"})
        if path.endswith("/roles/onboarding"):
            return httpx.Response(200, json={"id": "onboarding-id", "name": "onboarding"})
        if path.endswith("/roles/sales"):
            return httpx.Response(200, json={"id": "sales-id", "name": "sales"})
        if path.endswith("/users/user-1/role-mappings/realm") and request.method in {
            "DELETE",
            "POST",
        }:
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
        client = KeycloakAdminClient(settings, client=http)
        result = await client.stage_activation_target(user_id="user-1", expected_role="sales")
        await client.remove_onboarding_role(user_id="user-1")

    assert result == KeycloakActivation(user_id="user-1", role="sales")
    assert [(r.method, r.url.path.rsplit("/", 1)[-1]) for r in seen] == [
        ("POST", "token"),
        ("GET", "sales"),
        ("POST", "realm"),
        ("POST", "token"),
        ("GET", "onboarding"),
        ("DELETE", "realm"),
    ]


@pytest.mark.asyncio
async def test_keycloak_client_rejects_existing_user_without_mutating_roles_or_email():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        path = request.url.path
        if path.endswith("/protocol/openid-connect/token"):
            return httpx.Response(200, json={"access_token": "service-token"})
        if path.endswith("/admin/realms/aios/users") and request.method == "POST":
            return httpx.Response(409)
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
        with pytest.raises(KeycloakAdminConflict, match="keycloak_user_already_exists"):
            await KeycloakAdminClient(settings, client=http).invite_user(
                username="petrov",
                full_name="Петров Пётр",
                email="petrov@example.by",
                expected_department="Продажи",
                expected_role="sales",
            )

    assert [request.method for request in seen] == ["POST", "POST"]
