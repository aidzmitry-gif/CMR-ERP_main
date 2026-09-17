from __future__ import annotations

from types import SimpleNamespace

import jwt
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from config.access import IDENTITY_PROVISIONER_ROLE
from core.services import auth


def request(headers=None, core=None) -> Request:
    scope = {
        "type": "http", "method": "GET", "path": "/", "headers": [
            (key.lower().encode(), value.encode()) for key, value in (headers or {}).items()
        ],
    }
    if core is not None:
        scope["app"] = SimpleNamespace(state=SimpleNamespace(core=core))
    return Request(scope)


def test_oidc_validation_fail_closed_and_roles(monkeypatch):
    oidc = auth.OidcAuthenticator("https://issuer/", "erp")
    monkeypatch.setattr(oidc, "_signing_key", lambda _token: "key")
    monkeypatch.setattr(jwt, "decode", lambda *args, **kwargs: {
        "preferred_username": "ivan", "realm_access": {"roles": ["sales", ""]},
        "exp": 1, "iss": "x", "aud": "erp",
    })
    assert oidc.validate("token") == auth.CurrentUser("ivan", ["sales"])

    monkeypatch.setattr(jwt, "decode", lambda *_args, **_kwargs: {"sub": "user", "realm_access": {"roles": []}})
    assert oidc.validate("token").roles == [auth.GUEST]
    monkeypatch.setattr(jwt, "decode", lambda *_args, **_kwargs: (_ for _ in ()).throw(jwt.InvalidTokenError("bad")))
    assert oidc.validate("token") is None
    monkeypatch.setattr(jwt, "decode", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("jwks")))
    assert oidc.validate("token") is None


def test_dev_and_oidc_identity_helpers(monkeypatch):
    assert auth._bearer_token(request({"Authorization": "Bearer abc"})) == "abc"
    assert auth._bearer_token(request({"Authorization": "Basic abc"})) is None
    assert auth._roles_from_header(request({"X-User": "ivan", "X-User-Roles": "sales, director, "})) == auth.CurrentUser("ivan", ["sales", "director"])
    assert auth._roles_from_header(request()) == auth.CurrentUser("anonymous", [auth.GUEST])

    dev = SimpleNamespace(auth_mode="dev", keycloak_issuer="", keycloak_audience="")
    monkeypatch.setattr(auth, "get_settings", lambda: dev)
    assert auth.get_current_user(request({"X-User-Roles": "sales"})).roles == ["sales"]
    oidc = SimpleNamespace(auth_mode="oidc", keycloak_issuer="https://issuer", keycloak_audience="erp", keycloak_jwks_uri="")
    monkeypatch.setattr(auth, "get_settings", lambda: oidc)
    monkeypatch.setattr(auth, "_get_authenticator", lambda _settings: None)
    assert auth.get_current_user(request({"Authorization": "Bearer bad"})).roles == [auth.GUEST]
    assert auth._get_authenticator(SimpleNamespace(keycloak_issuer="", keycloak_audience="")) is None


def test_oidc_authenticator_builds_and_caches_jwk_client(monkeypatch):
    class Client:
        def __init__(self, uri):
            self.uri = uri

        def get_signing_key_from_jwt(self, _token):
            return SimpleNamespace(key="signing-key")

    monkeypatch.setattr("jwt.PyJWKClient", Client)
    oidc = auth.OidcAuthenticator("https://issuer/", "erp")
    assert oidc._signing_key("token") == "signing-key"
    assert oidc._signing_key("token-2") == "signing-key"
    assert oidc._jwk_client.uri == "https://issuer/protocol/openid-connect/certs"

    settings = SimpleNamespace(keycloak_issuer="https://issuer/", keycloak_audience="erp", keycloak_jwks_uri="")
    first = auth._get_authenticator(settings)
    assert first is auth._get_authenticator(settings)
    changed = SimpleNamespace(keycloak_issuer="https://issuer/", keycloak_audience="other", keycloak_jwks_uri="")
    assert auth._get_authenticator(changed) is not first


def test_permissions_cover_super_identity_and_module_roles():
    core = SimpleNamespace(roles=[SimpleNamespace(name="sales", permissions={"deal.read"})])
    assert auth.has_permission(core, auth.CurrentUser("a", ["director"]), "anything") is True
    assert auth.has_permission(core, auth.CurrentUser("a", [IDENTITY_PROVISIONER_ROLE]), "identity.invite.send") is True
    assert auth.has_permission(core, auth.CurrentUser("a", [IDENTITY_PROVISIONER_ROLE]), "deal.read") is False
    assert auth.has_permission(core, auth.CurrentUser("a", ["sales"]), "deal.read") is True
    assert auth.has_permission(core, auth.CurrentUser("a", ["sales"]), "deal.write") is False

    checker = auth.require_permission("deal.read")
    req = request(core=core)
    assert checker(req, auth.CurrentUser("a", ["sales"])).roles == ["sales"]
    with pytest.raises(HTTPException, match="Недостаточно прав"):
        checker(req, auth.CurrentUser("a", [auth.GUEST]))
