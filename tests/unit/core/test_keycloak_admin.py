from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from config.access import ONBOARDING_ROLE
from core.services.keycloak_admin import (
    KeycloakAdminClient,
    KeycloakAdminConflict,
    KeycloakAdminError,
    KeycloakAdminNotConfigured,
)


class Response:
    def __init__(self, status_code: int, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.headers = headers or {}

    def json(self):
        return self._payload


class Client:
    def __init__(self, *, posts=(), gets=(), puts=(), requests=(), error=None):
        self.posts = list(posts)
        self.gets = list(gets)
        self.puts = list(puts)
        self.requests = list(requests)
        self.error = error
        self.calls = []

    async def post(self, *args, **kwargs):
        self.calls.append(("post", args, kwargs))
        if self.error:
            raise self.error
        return self.posts.pop(0)

    async def get(self, *args, **kwargs):
        self.calls.append(("get", args, kwargs))
        return self.gets.pop(0)

    async def put(self, *args, **kwargs):
        self.calls.append(("put", args, kwargs))
        return self.puts.pop(0)

    async def request(self, *args, **kwargs):
        self.calls.append(("request", args, kwargs))
        return self.requests.pop(0)


def settings(**overrides):
    values = {
        "keycloak_admin_base_url": "https://keycloak.example/",
        "keycloak_admin_realm": "erp realm",
        "keycloak_admin_client_id": "admin-client",
        "keycloak_admin_client_secret": "secret",
        "keycloak_invite_client_id": "erp-web",
        "keycloak_invite_redirect_uri": "https://crm.example/callback",
        "keycloak_invite_lifespan_seconds": 900,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def client(**kwargs):
    return KeycloakAdminClient(settings(), client=Client(**kwargs))


def test_configuration_names_redirect_and_expectations():
    configured = client()
    assert configured.configured is True
    assert configured._safe_redirect_uri() is True
    assert KeycloakAdminClient._keycloak_names("Иван Петров") == ("Петров", "Иван")
    assert KeycloakAdminClient._keycloak_names("  ") == ("Сотрудник", "Сотрудник")
    KeycloakAdminClient._expect(Response(204), {204}, "unused")
    with pytest.raises(KeycloakAdminError) as exc:
        KeycloakAdminClient._expect(Response(500), {204}, "bad")
    assert exc.value.code == "bad"
    assert exc.value.upstream_status == 500

    assert KeycloakAdminClient(settings(keycloak_invite_redirect_uri="http://crm"))._safe_redirect_uri() is False
    assert KeycloakAdminClient(settings(keycloak_invite_redirect_uri="https://user:pass@crm"))._safe_redirect_uri() is False
    assert KeycloakAdminClient(settings(keycloak_invite_redirect_uri="https://crm/#fragment"))._safe_redirect_uri() is False


@pytest.mark.asyncio
async def test_invite_validates_configuration_and_runs_full_flow():
    fake = Client(
        posts=[
            Response(200, {"access_token": "token"}),
            Response(201, headers={"location": "https://keycloak/admin/realms/erp/users/u-1/"}),
            Response(204),
        ],
        gets=[Response(200, {"name": ONBOARDING_ROLE})],
        puts=[Response(204)],
    )
    api = KeycloakAdminClient(settings(), client=fake)
    invitation = await api.invite_user(
        username="ivan",
        full_name="Иван Петров",
        email="ivan@example.com",
        expected_department="sales",
        expected_role="sales_manager",
    )
    assert invitation.user_id == "u-1"
    assert invitation.reused is False
    assert invitation.actions == ("VERIFY_EMAIL", "UPDATE_PASSWORD")
    assert [call[0] for call in fake.calls] == ["post", "post", "get", "post", "put"]
    user_payload = fake.calls[1][2]["json"]
    assert user_payload["firstName"] == "Петров"
    assert user_payload["attributes"]["access_state"] == ["onboarding"]

    with pytest.raises(KeycloakAdminNotConfigured, match="not_configured"):
        await KeycloakAdminClient(settings(keycloak_admin_client_secret=""), client=fake).invite_user(
            username="u", full_name="U", email="u@x", expected_department="d", expected_role="r"
        )
    with pytest.raises(KeycloakAdminNotConfigured, match="redirect_uri_invalid"):
        await KeycloakAdminClient(settings(keycloak_invite_redirect_uri="http://bad"), client=fake).invite_user(
            username="u", full_name="U", email="u@x", expected_department="d", expected_role="r"
        )
    with pytest.raises(KeycloakAdminNotConfigured, match="too_short"):
        await KeycloakAdminClient(settings(keycloak_invite_lifespan_seconds=10), client=fake).invite_user(
            username="u", full_name="U", email="u@x", expected_department="d", expected_role="r"
        )


@pytest.mark.asyncio
async def test_service_token_and_user_creation_errors_are_safe():
    api = client(posts=[Response(200, {})])
    with pytest.raises(KeycloakAdminError, match="token_missing"):
        await api._service_token(api._client)

    api = client(posts=[Response(500)])
    with pytest.raises(KeycloakAdminError, match="token_failed"):
        await api._service_token(api._client)

    api = client(posts=[Response(409)])
    with pytest.raises(KeycloakAdminConflict, match="already_exists"):
        await api._ensure_user(
            api._client,
            admin="https://admin",
            headers={},
            username="u",
            full_name="User",
            email="u@x",
            expected_department="d",
            expected_role="r",
        )

    api = client(posts=[Response(201, headers={"location": "https://admin/users"})])
    with pytest.raises(KeycloakAdminError, match="user_id_missing"):
        await api._ensure_user(
            api._client,
            admin="https://admin",
            headers={},
            username="u",
            full_name="User",
            email="u@x",
            expected_department="d",
            expected_role="r",
        )


@pytest.mark.asyncio
async def test_activation_and_cleanup_use_expected_roles():
    fake = Client(
        posts=[Response(200, {"access_token": "token"}), Response(204), Response(200, {"access_token": "token"})],
        gets=[Response(200, {"name": "sales_manager"}), Response(200, {"name": ONBOARDING_ROLE})],
        requests=[Response(204)],
    )
    api = KeycloakAdminClient(settings(), client=fake)
    activation = await api.stage_activation_target(user_id="u-1", expected_role="sales_manager")
    assert activation.user_id == "u-1"
    await api.remove_onboarding_role(user_id="u-1")
    assert [call[0] for call in fake.calls] == ["post", "get", "post", "post", "get", "request"]

    with pytest.raises(KeycloakAdminError, match="state_invalid"):
        await api.stage_activation_target(user_id="", expected_role="sales_manager")
    with pytest.raises(KeycloakAdminError, match="state_invalid"):
        await api.remove_onboarding_role(user_id="")
    with pytest.raises(KeycloakAdminError, match="state_invalid"):
        await api.stage_activation_target(user_id="u", expected_role=ONBOARDING_ROLE)


@pytest.mark.asyncio
async def test_transport_failures_are_wrapped_without_leaking_response():
    api = client(error=httpx.ConnectError("offline"))
    with pytest.raises(KeycloakAdminError, match="invite_transport_failed"):
        await api.invite_user(
            username="u", full_name="U", email="u@x", expected_department="d", expected_role="r"
        )
    with pytest.raises(KeycloakAdminError, match="activation_transport_failed"):
        await api.stage_activation_target(user_id="u", expected_role="sales_manager")
    with pytest.raises(KeycloakAdminError, match="cleanup_transport_failed"):
        await api.remove_onboarding_role(user_id="u")
