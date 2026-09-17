from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from starlette.requests import Request

from config.access import ONBOARDING_ROLE
from core.domain.models import (
    IdentityAccessActivationRequest,
    IdentityInvitationRequest,
    User,
)
from core.runtime import identity_routes
from core.services.auth import CurrentUser
from core.services.keycloak_admin import (
    KeycloakAdminConflict,
    KeycloakAdminError,
    KeycloakAdminNotConfigured,
    KeycloakInvitation,
)
from modules.hr.models import Employee


class Result:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def scalars(self):
        return self

    def all(self):
        return self.rows

    def scalar_one_or_none(self):
        return self.rows[0] if self.rows else None


class Session:
    def __init__(self, *results):
        self.results = list(results)
        self.added = []
        self.commits = 0
        self.rollbacks = 0
        self.refreshed = []

    async def execute(self, _statement):
        return self.results.pop(0) if self.results else Result()

    async def get(self, _model, _identity):
        return None

    def add(self, value):
        if getattr(value, "id", None) is None:
            value.id = 100 + len(self.added)
        self.added.append(value)

    async def flush(self):
        for value in self.added:
            if getattr(value, "id", None) is None:
                value.id = 100 + self.added.index(value)

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1

    async def refresh(self, value):
        self.refreshed.append(value)


def request_with_key(value="invite-2026-0001"):
    return Request({"type": "http", "method": "POST", "path": "/", "headers": [(b"idempotency-key", value.encode())]})


def invite_payload(**changes):
    values = {"employee_id": 7, "email": "user@example.com", "department": "Продажи", "role": "sales"}
    values.update(changes)
    return identity_routes.InviteEmployeeIn(**values)


def employee():
    return Employee(id=7, full_name="Иван Петров", department="Продажи", status="active")


def onboarding_user():
    return User(
        id=10, username="user", full_name="Иван Петров", email="user@example.com", employee_id=7,
        department=None, role=ONBOARDING_ROLE, expected_department="Продажи", expected_role="sales",
        keycloak_user_id="kc-10", status="onboarding",
    )


@pytest.mark.asyncio
async def test_identity_departments_preflight_invite_success_and_failed_upstream_are_idempotent():
    departments = await identity_routes.identity_departments(CurrentUser("director", ["director"]))
    assert "Продажи" in departments["departments"]

    emp = employee()
    payload = invite_payload()
    preflight = await identity_routes.preflight_invitation(payload, CurrentUser("director", ["director"]), Session(Result([emp]), Result([])))
    assert preflight.ready is True and preflight.username == "user"

    identity = SimpleNamespace(
        invite_user=AsyncMock(return_value=KeycloakInvitation("kc-10", "user", "user@example.com", ONBOARDING_ROLE, (), False)),
    )
    actor = CurrentUser("director", ["director"])
    session = Session(Result([emp]), Result([]), Result(), Result())
    invited = await identity_routes.invite_employee(payload, request_with_key(), actor, session, identity)
    assert (invited.status, invited.role, invited.expected_department, invited.expected_role) == (
        "onboarding", ONBOARDING_ROLE, "Продажи", "sales"
    )
    identity.invite_user.assert_awaited_once()
    assert session.commits == 2

    failed_identity = SimpleNamespace(invite_user=AsyncMock(side_effect=KeycloakAdminNotConfigured("keycloak_admin_not_configured")))
    failed_session = Session(Result([emp]), Result([]), Result(), Result())
    with pytest.raises(HTTPException, match="keycloak_admin_not_configured") as error:
        await identity_routes.invite_employee(payload, request_with_key("invite-2026-0002"), actor, failed_session, failed_identity)
    assert error.value.status_code == 503
    assert failed_session.commits == 2


@pytest.mark.asyncio
async def test_identity_invite_replays_safe_result_and_rejects_conflicts():
    emp = employee()
    sent_user = onboarding_user()
    same = IdentityInvitationRequest(
        id=1, idempotency_key="invite-2026-0001", employee_id=7, username="user", email="user@example.com",
        department="Продажи", role="sales", actor="director", status="sent", user_id=10,
    )

    class ReplaySession(Session):
        async def get(self, _model, _identity):
            return sent_user

    replay = await identity_routes.invite_employee(
        invite_payload(), request_with_key(), CurrentUser("director", ["director"]),
        ReplaySession(Result([emp]), Result([]), Result([same])), SimpleNamespace(invite_user=AsyncMock()),
    )
    assert replay is sent_user

    occupied = User(id=11, username="other", full_name="Другой", email="user@example.com", employee_id=8, department="Продажи", role="sales", expected_department="Продажи", expected_role="sales", status="active")
    with pytest.raises(HTTPException, match="занят"):
        await identity_routes.preflight_invitation(
            invite_payload(), CurrentUser("director", ["director"]), Session(Result([emp]), Result([occupied]))
        )


@pytest.mark.asyncio
async def test_identity_activation_stages_role_removes_onboarding_and_replays_without_external_repeat():
    user = onboarding_user()
    emp = employee()
    identity = SimpleNamespace(stage_activation_target=AsyncMock(), remove_onboarding_role=AsyncMock())
    actor = CurrentUser("director", ["director"])
    session = Session(
        Result([user]), Result(), Result([emp]), Result(), Result([user]), Result([emp])
    )
    activated = await identity_routes.activate_employee(7, request_with_key("activate-2026-0001"), actor, session, identity)
    assert (activated.status, activated.department, activated.role, activated.expected_role) == (
        "active", "Продажи", "sales", None
    )
    identity.stage_activation_target.assert_awaited_once_with(user_id="kc-10", expected_role="sales")
    identity.remove_onboarding_role.assert_awaited_once_with(user_id="kc-10")
    assert session.commits == 3

    successful = IdentityAccessActivationRequest(
        id=2, idempotency_key="activate-2026-0002", user_id=10, employee_id=7,
        expected_department="Продажи", expected_role="sales", actor="director", status="succeeded",
    )
    active = User(id=10, username="user", full_name="Иван Петров", email="user@example.com", employee_id=7, department="Продажи", role="sales", expected_department=None, expected_role=None, status="active")
    class ActiveReplaySession(Session):
        async def get(self, _model, _identity):
            return active

    replay = await identity_routes.activate_employee(
        7, request_with_key("activate-2026-0002"), actor,
        ActiveReplaySession(Result([active]), Result([successful])), identity,
    )
    assert replay is active


class SessionWithUser(Session):
    def __init__(self, user, *results):
        super().__init__(*results)
        self.user = user

    async def get(self, _model, _identity):
        return self.user


class CommitFailSession(Session):
    def __init__(self, fail_at, *results):
        super().__init__(*results)
        self.fail_at = fail_at

    async def commit(self):
        self.commits += 1
        if self.commits == self.fail_at:
            raise RuntimeError("database commit failed")


class FlushFailSession(Session):
    async def flush(self):
        raise RuntimeError("database flush failed")


def valid_activation_results(*, user=None, employee_value=None, existing=None):
    user = user or onboarding_user()
    employee_value = employee_value or employee()
    return (
        Result([user]),
        Result(),
        Result([employee_value]),
        Result([existing] if existing is not None else []),
    )


@pytest.mark.asyncio
async def test_identity_gateway_resolve_guards_and_read_reconciliation_paths(monkeypatch):
    sentinel = object()
    monkeypatch.setattr(identity_routes, "KeycloakAdminClient", lambda config: sentinel)
    gateway_request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(core=SimpleNamespace(services=SimpleNamespace(config="cfg"))))
    )
    assert identity_routes.get_identity_gateway(gateway_request) is sentinel

    payload = invite_payload()
    cases = [
        (Session(Result()), 404, "Сотрудник"),
        (Session(Result([SimpleNamespace(status="inactive", department="Продажи")])), 409, "активного"),
        (Session(Result([SimpleNamespace(status="active", department=None)])), 422, "отдел"),
        (Session(Result([SimpleNamespace(status="active", department="Закупки")])), 422, "совпадать"),
    ]
    for session, status, fragment in cases:
        with pytest.raises(HTTPException, match=fragment) as error:
            await identity_routes.preflight_invitation(payload, CurrentUser("director", ["director"]), session)
        assert error.value.status_code == status

    bad_role_employee = SimpleNamespace(status="active", department="Продажи")
    with pytest.raises(HTTPException, match="Роль не разрешена") as error:
        await identity_routes.preflight_invitation(
            invite_payload(role="warehouse"), CurrentUser("director", ["director"]),
            Session(Result([bad_role_employee])),
        )
    assert error.value.status_code == 422

    conflicting_user = User(
        id=10, username="user", email="user@example.com", employee_id=7,
        department=None, role="sales", expected_department="Продажи", expected_role="sales",
    )
    with pytest.raises(HTTPException, match="другой identity") as error:
        await identity_routes.preflight_invitation(
            payload, CurrentUser("director", ["director"]), Session(Result([employee()]), Result([conflicting_user]))
        )
    assert error.value.status_code == 409

    with pytest.raises(HTTPException, match="ручной сверки"):
        await identity_routes._request_result_user(
            Session(), IdentityInvitationRequest(status="sent", user_id=10)
        )

    with pytest.raises(HTTPException, match="обрабатывается"):
        await identity_routes._activation_result_user(
            Session(), IdentityAccessActivationRequest(status="sending", user_id=10)
        )

    rows = [User(id=1, username="user", status="onboarding")]
    assert await identity_routes.list_invitations(CurrentUser("director", ["director"]), Session(Result(rows))) == rows


@pytest.mark.asyncio
async def test_identity_invitation_conflicts_upstream_errors_and_reconciliation(monkeypatch):
    actor = CurrentUser("director", ["director"])
    emp = employee()
    same_key = IdentityInvitationRequest(
        id=1, idempotency_key="invite-2026-0001", employee_id=7, username="other",
        email="user@example.com", department="Продажи", role="sales", status="sending",
    )
    with pytest.raises(HTTPException, match="другими данными") as error:
        await identity_routes.invite_employee(
            invite_payload(), request_with_key(), actor,
            Session(Result([emp]), Result([]), Result([same_key])), SimpleNamespace(invite_user=AsyncMock()),
        )
    assert error.value.status_code == 409

    replay_user = onboarding_user()
    replay_user.invited_at = datetime(2026, 1, 1)
    assert await identity_routes.invite_employee(
        invite_payload(), request_with_key("invite-2026-0002"), actor,
        Session(Result([emp]), Result([replay_user]), Result()), SimpleNamespace(invite_user=AsyncMock()),
    ) is replay_user

    manual_user = onboarding_user()
    manual_user.invited_at = None
    with pytest.raises(HTTPException, match="ручной сверки") as error:
        await identity_routes.invite_employee(
            invite_payload(), request_with_key("invite-2026-0003"), actor,
            Session(Result([emp]), Result([manual_user]), Result()), SimpleNamespace(invite_user=AsyncMock()),
        )
    assert error.value.status_code == 409

    sent = onboarding_user()
    invitation = IdentityInvitationRequest(
        id=2, idempotency_key="invite-2026-0004", employee_id=7, username="user",
        email="user@example.com", department="Продажи", role="sales", status="sent", user_id=10,
    )
    assert await identity_routes.invite_employee(
        invite_payload(), request_with_key("invite-2026-0004"), actor,
        SessionWithUser(sent, Result([emp]), Result([]), Result(),),
        SimpleNamespace(invite_user=AsyncMock()),
    ) is not sent

    # Employee-level request replay is reached only after the idempotency-key lookup misses.
    class EmployeeRequestSession(SessionWithUser):
        pass

    replay_session = EmployeeRequestSession(
        sent, Result([emp]), Result([]), Result(), Result([invitation])
    )
    assert await identity_routes.invite_employee(
        invite_payload(), request_with_key("invite-2026-0005"), actor,
        replay_session, SimpleNamespace(invite_user=AsyncMock()),
    ) is sent

    mismatch_request = IdentityInvitationRequest(
        id=3, employee_id=7, username="user", email="user@example.com",
        department="Продажи", role="sales", status="sending", user_id=None,
    )
    with pytest.raises(HTTPException, match="отдельной операции"):
        await identity_routes.invite_employee(
            invite_payload(role="sales_cli"), request_with_key("invite-2026-0006"), actor,
            Session(Result([emp]), Result([]), Result(), Result([mismatch_request])),
            SimpleNamespace(invite_user=AsyncMock()),
        )

    integrity = CommitFailSession(1, Result([emp]), Result([]), Result())
    integrity.commit = AsyncMock(side_effect=IntegrityError("insert", {}, RuntimeError("duplicate")))
    with pytest.raises(HTTPException, match="уже создана") as error:
        await identity_routes.invite_employee(
            invite_payload(), request_with_key("invite-2026-0007"), actor, integrity,
            SimpleNamespace(invite_user=AsyncMock()),
        )
    assert error.value.status_code == 409 and integrity.rollbacks == 1

    for key, upstream_error, expected_status in [
        ("invite-2026-0008", KeycloakAdminConflict("keycloak_user_conflict"), 409),
        ("invite-2026-0009", KeycloakAdminError("keycloak_invite_failed"), 502),
    ]:
        session = Session(Result([emp]), Result([]), Result(), Result())
        identity = SimpleNamespace(invite_user=AsyncMock(side_effect=upstream_error))
        with pytest.raises(HTTPException) as error:
            await identity_routes.invite_employee(
                invite_payload(), request_with_key(key), actor, session, identity
            )
        assert error.value.status_code == expected_status

    flush_failure = FlushFailSession(Result([emp]), Result([]), Result(), Result())
    with pytest.raises(HTTPException, match="reconciliation") as error:
        await identity_routes.invite_employee(
            invite_payload(), request_with_key("invite-2026-0010"), actor, flush_failure,
            SimpleNamespace(invite_user=AsyncMock(return_value=KeycloakInvitation("kc", "user", "user@example.com", ONBOARDING_ROLE, (), False))),
        )
    assert error.value.status_code == 502 and flush_failure.rollbacks == 1


@pytest.mark.asyncio
async def test_identity_activation_guards_upstream_and_state_drift(monkeypatch):
    actor = CurrentUser("director", ["director"])
    identity = SimpleNamespace(
        stage_activation_target=AsyncMock(),
        remove_onboarding_role=AsyncMock(),
    )

    with pytest.raises(HTTPException) as error:
        await identity_routes.activate_employee(
            7, request_with_key("activate-2026-0101"), actor, Session(Result()), identity
        )
    assert error.value.status_code == 404

    user = onboarding_user()
    conflict = IdentityAccessActivationRequest(
        id=1, idempotency_key="activate-2026-0102", user_id=99, employee_id=7,
        expected_department="Продажи", expected_role="sales", status="succeeded",
    )
    with pytest.raises(HTTPException, match="другой активацией") as error:
        await identity_routes.activate_employee(
            7, request_with_key("activate-2026-0102"), actor,
            Session(Result([user]), Result([conflict])), identity,
        )
    assert error.value.status_code == 409

    drifted = onboarding_user()
    drifted.status = "active"
    with pytest.raises(HTTPException, match="изменено") as error:
        await identity_routes.activate_employee(
            7, request_with_key("activate-2026-0103"), actor,
            Session(Result([drifted]), Result()), identity,
        )
    assert error.value.status_code == 409

    with pytest.raises(HTTPException, match="HR") as error:
        await identity_routes.activate_employee(
            7, request_with_key("activate-2026-0104"), actor,
            Session(*valid_activation_results(employee_value=SimpleNamespace(status="inactive", department="Продажи"))),
            identity,
        )
    assert error.value.status_code == 409

    active_user = User(
        id=10, username="user", employee_id=7, status="active", department="Продажи", role="sales",
        expected_department=None, expected_role=None,
    )
    existing = IdentityAccessActivationRequest(
        id=2, user_id=10, employee_id=7, expected_department="Продажи", expected_role="sales", status="succeeded"
    )
    replay_session = SessionWithUser(active_user, *valid_activation_results(existing=existing))
    assert await identity_routes.activate_employee(
        7, request_with_key("activate-2026-0105"), actor, replay_session, identity
    ) is active_user

    mismatch_existing = IdentityAccessActivationRequest(
        id=3, user_id=10, employee_id=7, expected_department="Продажи", expected_role="director", status="sending"
    )
    with pytest.raises(HTTPException, match="ручная сверка") as error:
        await identity_routes.activate_employee(
            7, request_with_key("activate-2026-0106"), actor,
            Session(*valid_activation_results(existing=mismatch_existing)), identity,
        )
    assert error.value.status_code == 409

    integrity = CommitFailSession(1, *valid_activation_results())
    integrity.commit = AsyncMock(side_effect=IntegrityError("insert", {}, RuntimeError("duplicate")))
    with pytest.raises(HTTPException, match="уже создана") as error:
        await identity_routes.activate_employee(
            7, request_with_key("activate-2026-0107"), actor, integrity, identity
        )
    assert error.value.status_code == 409 and integrity.rollbacks == 1

    for key, upstream_error, expected_status in [
        ("activate-2026-0108", KeycloakAdminNotConfigured("keycloak_not_configured"), 503),
        ("activate-2026-0109", KeycloakAdminError("keycloak_stage_failed"), 502),
    ]:
        session = Session(*valid_activation_results())
        failing = SimpleNamespace(stage_activation_target=AsyncMock(side_effect=upstream_error))
        with pytest.raises(HTTPException) as error:
            await identity_routes.activate_employee(7, request_with_key(key), actor, session, failing)
        assert error.value.status_code == expected_status

    drift_user = onboarding_user()
    drift_user.expected_role = "director"
    drift_session = Session(
        *valid_activation_results(), Result([drift_user]), Result([employee()])
    )
    with pytest.raises(HTTPException, match="во время активации") as error:
        await identity_routes.activate_employee(
            7, request_with_key("activate-2026-0110"), actor, drift_session, identity
        )
    assert error.value.status_code == 409
