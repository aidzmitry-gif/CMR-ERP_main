from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from config.access import ONBOARDING_ROLE
from core.domain.models import IdentityInvitationRequest
from core.runtime import identity_routes
from core.services.auth import CurrentUser


def request_with_key(value: str) -> Request:
    return Request({"type": "http", "method": "POST", "path": "/", "headers": [(b"idempotency-key", value.encode())]})


def payload(**kwargs):
    values = {"employee_id": 7, "email": " User@Example.COM ", "department": "Продажи", "role": "sales"}
    values.update(kwargs)
    return identity_routes.InviteEmployeeIn(**values)


def test_identity_payload_normalization_and_guards():
    body = payload(username=" Ivan_User ")
    assert body.email == "user@example.com"
    assert body.username == "Ivan_User"
    assert identity_routes._username(body) == "ivan_user"
    with pytest.raises(HTTPException, match="логин"):
        identity_routes._username(payload(username="Иван Петров"))

    with pytest.raises(HTTPException, match="логин"):
        identity_routes._username(payload(username="!!"))
    with pytest.raises(ValueError, match="email"):
        payload(email="bad")

    user = SimpleNamespace(
        username="user", email="user@example.com", department=None, role=ONBOARDING_ROLE,
        expected_department="Продажи", expected_role="sales",
    )
    assert identity_routes._same_user_payload(user, payload(username="user"), "user") is True
    invite = SimpleNamespace(employee_id=7, username="user", email="user@example.com", department="Продажи", role="sales")
    assert identity_routes._same_request_payload(invite, payload(username="user"), "user") is True

    assert identity_routes._idempotency_key(request_with_key("invite-2026-0001")) == "invite-2026-0001"
    with pytest.raises(HTTPException, match="Idempotency-Key"):
        identity_routes._idempotency_key(request_with_key("short"))


@pytest.mark.asyncio
async def test_identity_request_result_guards_and_failure_audit():
    invite = IdentityInvitationRequest(
        idempotency_key="invite-2026-0001", employee_id=7, username="user",
        email="user@example.com", department="Продажи", role="sales", actor="admin", status="sent",
    )
    invite.id = 1
    invite.user_id = 10
    user = SimpleNamespace(id=10)

    class Session:
        def __init__(self):
            self.added = []
            self.commits = 0

        async def get(self, _model, _identity):
            return user

        def add(self, value):
            self.added.append(value)

        async def commit(self):
            self.commits += 1

    session = Session()
    assert await identity_routes._request_result_user(session, invite) is user
    with pytest.raises(HTTPException, match="повтор не отправлен"):
        await identity_routes._request_result_user(session, SimpleNamespace(status="sending", user_id=None))
    await identity_routes._failed_request(session, invite, actor=CurrentUser("admin", ["director"]), code="upstream")
    assert invite.status == "failed"
    assert session.commits == 1
    assert session.added[-1].action == "identity.user.invitation_failed"

    activation = SimpleNamespace(
        status="succeeded", user_id=10, employee_id=7, expected_department="Продажи", expected_role="sales",
    )
    active_user = SimpleNamespace(
        id=10, status="active", department="Продажи", role="sales",
        expected_department=None, expected_role=None, employee_id=7,
    )
    class ActivationSession(Session):
        async def get(self, _model, _identity):
            return active_user

    assert await identity_routes._activation_result_user(ActivationSession(), activation) is active_user
    with pytest.raises(HTTPException, match="не согласован"):
        await identity_routes._activation_result_user(
            ActivationSession(), SimpleNamespace(status="succeeded", user_id=10, expected_department="HR", expected_role="hr")
        )
