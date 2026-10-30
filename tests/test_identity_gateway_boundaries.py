"""Identity gateway refusals must not grant access or retry uncertain writes."""
import json
from types import SimpleNamespace

import httpx
import pytest

from core.services import keycloak_admin
from core.services.keycloak_admin import KeycloakAdminClient, KeycloakAdminError


def _settings(**changes):
    return SimpleNamespace(**{
        "keycloak_admin_base_url": "https://identity.example.invalid",
        "keycloak_admin_realm": "synthetic",
        "keycloak_admin_client_id": "synthetic-gateway",
        "keycloak_admin_client_secret": "synthetic-test-value",
        "keycloak_invite_client_id": "synthetic-erp",
        "keycloak_invite_redirect_uri": "https://erp.example.invalid/",
        "keycloak_invite_lifespan_seconds": 600,
        **changes,
    })


OPERATIONS = [
    ("set_user_enabled", {"user_id": "synthetic-user", "enabled": False, "expected_role": "sales"},
     "keycloak_access_change_transport_failed"),
    ("invite_user", {"username": "synthetic-user", "full_name": "Synthetic Employee",
                     "email": "synthetic@example.invalid", "expected_department": "Продажи",
                     "expected_role": "sales"}, "keycloak_invite_transport_failed"),
    ("stage_activation_target", {"user_id": "synthetic-user", "expected_role": "sales"},
     "keycloak_activation_transport_failed"),
    ("validate_activation_ready", {"user_id": "synthetic-user", "expected_role": "sales"},
     "keycloak_activation_readiness_transport_failed"),
    ("remove_onboarding_role", {"user_id": "synthetic-user"},
     "keycloak_activation_cleanup_transport_failed"),
    ("change_crm_role", {"user_id": "synthetic-user", "current_role": "sales", "target_role": "sales_head"},
     "keycloak_crm_role_change_transport_failed"),
]


@pytest.mark.parametrize("method, arguments, _error", OPERATIONS)
async def test_incomplete_configuration_never_contacts_identity_provider(method, arguments, _error):
    seen = []

    def reject(request):
        seen.append(request)
        pytest.fail("Unconfigured identity gateway attempted an external request")

    async with httpx.AsyncClient(transport=httpx.MockTransport(reject)) as client:
        gateway = KeycloakAdminClient(_settings(keycloak_admin_client_secret=""), client=client)
        with pytest.raises(KeycloakAdminError) as error:
            await getattr(gateway, method)(**arguments)
        assert error.value.code == "keycloak_admin_not_configured"
    assert seen == []


@pytest.mark.parametrize("method, arguments, expected_error", OPERATIONS)
async def test_owned_http_client_is_closed_after_transport_failure_without_retry(
    method, arguments, expected_error, monkeypatch,
):
    requests, construction = [], []

    def fail(request):
        requests.append((request.method, request.url.path))
        raise httpx.ReadTimeout("Synthetic provider timeout", request=request)

    owned = httpx.AsyncClient(transport=httpx.MockTransport(fail))

    def factory(**kwargs):
        construction.append(kwargs)
        return owned

    monkeypatch.setattr(keycloak_admin.httpx, "AsyncClient", factory)
    gateway = KeycloakAdminClient(_settings())
    with pytest.raises(KeycloakAdminError) as error:
        await getattr(gateway, method)(**arguments)
    assert error.value.code == expected_error
    assert len(requests) == 1 and requests[0][1].endswith("/token")
    assert construction == [{"timeout": 15.0}]
    assert owned.is_closed


@pytest.mark.parametrize("method, arguments, code", [
    ("set_user_enabled", {"user_id": "", "enabled": False, "expected_role": "sales"}, "keycloak_access_change_invalid"),
    ("set_user_enabled", {"user_id": "synthetic", "enabled": True, "expected_role": "director"}, "keycloak_access_change_invalid"),
    ("stage_activation_target", {"user_id": "", "expected_role": "sales"}, "keycloak_activation_state_invalid"),
    ("stage_activation_target", {"user_id": "synthetic", "expected_role": "onboarding"}, "keycloak_activation_state_invalid"),
    ("remove_onboarding_role", {"user_id": ""}, "keycloak_activation_state_invalid"),
    ("change_crm_role", {"user_id": "", "current_role": "sales", "target_role": "sales_head"}, "keycloak_crm_role_change_invalid"),
    ("change_crm_role", {"user_id": "synthetic", "current_role": "director", "target_role": "sales"}, "keycloak_crm_role_change_invalid"),
    ("change_crm_role", {"user_id": "synthetic", "current_role": "sales", "target_role": "director"}, "keycloak_crm_role_change_invalid"),
])
async def test_invalid_target_is_refused_before_token_request(method, arguments, code):
    def reject(_request):
        pytest.fail("Invalid identity target reached the provider")

    async with httpx.AsyncClient(transport=httpx.MockTransport(reject)) as client:
        with pytest.raises(KeycloakAdminError) as error:
            await getattr(KeycloakAdminClient(_settings(), client=client), method)(**arguments)
    assert error.value.code == code


@pytest.mark.parametrize("user_changes, sessions, roles, expected", [
    ({"id": "another-user"}, [{}], [{"name": "onboarding"}], "keycloak_activation_first_login_required"),
    ({"enabled": False}, [{}], [{"name": "onboarding"}], "keycloak_activation_first_login_required"),
    ({"emailVerified": False}, [{}], [{"name": "onboarding"}], "keycloak_activation_first_login_required"),
    ({"requiredActions": ["UPDATE_PASSWORD"]}, [{}], [{"name": "onboarding"}], "keycloak_activation_first_login_required"),
    ({"attributes": None}, [{}], [{"name": "onboarding"}], "keycloak_activation_state_drift"),
    ({"attributes": {"expected_role": ["sales_head"]}}, [{}], [{"name": "onboarding"}], "keycloak_activation_state_drift"),
    ({}, [], [{"name": "onboarding"}], "keycloak_activation_first_login_required"),
    ({}, {}, [{"name": "onboarding"}], "keycloak_activation_first_login_required"),
    ({}, [{}], {"name": "onboarding"}, "keycloak_access_role_verify_mismatch"),
    ({}, [{}], [{"name": 7}], "keycloak_access_role_verify_mismatch"),
    ({}, [{}], [{"name": "sales"}], "keycloak_access_role_state_drift"),
    ({}, [{}], [{"name": "onboarding"}, {"name": "director"}], "keycloak_access_role_state_drift"),
])
async def test_readiness_requires_completed_first_login_and_exact_onboarding_role(
    user_changes, sessions, roles, expected,
):
    seen = []

    def handle(request):
        seen.append((request.method, request.url.path))
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "synthetic-access"})
        assert request.method == "GET", "Readiness may never mutate the provider"
        if request.url.path.endswith("/sessions"):
            return httpx.Response(200, json=sessions)
        if request.url.path.endswith("/composite"):
            return httpx.Response(200, json=roles)
        return httpx.Response(200, json={
            "id": "synthetic-user", "enabled": True, "emailVerified": True,
            "requiredActions": [], "attributes": {"expected_role": ["sales"]}, **user_changes,
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(KeycloakAdminError) as error:
            await KeycloakAdminClient(_settings(), client=client).validate_activation_ready(
                user_id="synthetic-user", expected_role="sales",
            )
    assert error.value.code == expected
    assert all(method == "GET" or path.endswith("/token") for method, path in seen)


@pytest.mark.parametrize("redirect", [
    "http://erp.example.invalid/", "https://user@erp.example.invalid/",
    "https://user:password@erp.example.invalid/", "https://erp.example.invalid/#fragment", "/relative",
])
async def test_invitation_rejects_unsafe_callback_before_creating_user(redirect):
    def reject(_request):
        pytest.fail("Unsafe callback reached the provider")

    async with httpx.AsyncClient(transport=httpx.MockTransport(reject)) as client:
        gateway = KeycloakAdminClient(_settings(keycloak_invite_redirect_uri=redirect), client=client)
        with pytest.raises(KeycloakAdminError) as error:
            await gateway.invite_user(**OPERATIONS[1][1])
    assert error.value.code == "keycloak_invite_redirect_uri_invalid"


@pytest.mark.parametrize("token_body, create_status, location, expected", [
    ({}, 201, "/users/synthetic-user", "keycloak_admin_token_missing"),
    ({"access_token": "synthetic-access"}, 201, "", "keycloak_created_user_id_missing"),
    ({"access_token": "synthetic-access"}, 201, "/users/", "keycloak_created_user_id_missing"),
    ({"access_token": "synthetic-access"}, 500, "", "keycloak_user_create_failed"),
])
async def test_ambiguous_invitation_response_never_assigns_role_or_sends_email(
    token_body, create_status, location, expected,
):
    requests = []

    def handle(request):
        requests.append((request.method, request.url.path))
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json=token_body)
        assert request.method == "POST" and request.url.path.endswith("/users")
        assert json.loads(request.content)["requiredActions"] == ["VERIFY_EMAIL", "UPDATE_PASSWORD"]
        return httpx.Response(create_status, headers={"Location": location})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(KeycloakAdminError) as error:
            await KeycloakAdminClient(_settings(), client=client).invite_user(**OPERATIONS[1][1])
    assert error.value.code == expected
    assert len(requests) == (1 if not token_body else 2)
