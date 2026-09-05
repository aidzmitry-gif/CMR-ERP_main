"""AuthN: dev доверяет заголовку, oidc валидирует Keycloak-JWT (fail-closed «Гость»).

Юнит-проверки ``OidcAuthenticator.validate`` (подпись/iss/aud/exp) на сгенерированном
RSA-ключе без сети + dev/oidc-ветки ``get_current_user``.
"""
from __future__ import annotations

import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from core.services import auth as auth_mod
from core.services.auth import GUEST, OidcAuthenticator, get_current_user

ISS = "https://kc.example/realms/aios"
AUD = "aios-app"


@pytest.fixture(scope="module")
def keys():
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv_pem = priv.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    pub_pem = priv.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return priv_pem, pub_pem


def _token(priv_pem, **overrides):
    now = int(time.time())
    payload = {
        "iss": ISS,
        "aud": AUD,
        "exp": now + 3600,
        "sub": "kc-ivanov-uuid",
        "preferred_username": "ivanov",
        "realm_access": {"roles": ["sales", "Менеджер"]},
    }
    payload.update(overrides)
    return jwt.encode(payload, priv_pem, algorithm="RS256")


@pytest.fixture
def authn(keys):
    _, pub_pem = keys
    a = OidcAuthenticator(ISS, AUD)
    a._signing_key = lambda token: pub_pem  # без сети: фиксированный публичный ключ
    return a


def _oidc_settings(monkeypatch):
    monkeypatch.setattr(
        auth_mod,
        "get_settings",
        lambda: SimpleNamespace(
            auth_mode="oidc",
            keycloak_issuer=ISS,
            keycloak_audience=AUD,
            keycloak_jwks_uri="",
        ),
    )


# --- OidcAuthenticator.validate ---
def test_valid_token_yields_user_and_roles(authn, keys):
    priv_pem, _ = keys
    user = authn.validate(_token(priv_pem))
    assert user is not None
    assert user.username == "ivanov"
    assert user.roles == ["sales", "Менеджер"]


def test_expired_token_rejected(authn, keys):
    priv_pem, _ = keys
    # просрочка за пределами leeway (=30с): токен, истёкший час назад
    assert authn.validate(_token(priv_pem, exp=int(time.time()) - 3600)) is None


def test_wrong_audience_rejected(authn, keys):
    priv_pem, _ = keys
    assert authn.validate(_token(priv_pem, aud="other-client")) is None


def test_wrong_issuer_rejected(authn, keys):
    priv_pem, _ = keys
    assert authn.validate(_token(priv_pem, iss="https://evil/realms/x")) is None


def test_garbage_token_rejected(authn):
    assert authn.validate("not-a-jwt") is None


def test_token_without_roles_is_guest(authn, keys):
    priv_pem, _ = keys
    user = authn.validate(_token(priv_pem, realm_access={"roles": []}))
    assert user is not None and user.roles == [GUEST]


@pytest.mark.parametrize("subject", [None, "", "   "])
def test_token_without_nonempty_string_subject_is_rejected(authn, keys, subject):
    priv_pem, _ = keys
    assert authn.validate(_token(priv_pem, sub=subject)) is None


# --- ветки get_current_user ---
def test_dev_mode_trusts_header(monkeypatch):
    monkeypatch.setattr(auth_mod, "get_settings", lambda: SimpleNamespace(auth_mode="dev"))
    req = SimpleNamespace(headers={"X-User-Roles": "sales", "X-User": "ivanov"})
    user = get_current_user(req)
    assert user.roles == ["sales"] and user.username == "ivanov"


def test_dev_mode_no_header_is_guest(monkeypatch):
    monkeypatch.setattr(auth_mod, "get_settings", lambda: SimpleNamespace(auth_mode="dev"))
    user = get_current_user(SimpleNamespace(headers={}))
    assert user.roles == [GUEST]


def test_oidc_mode_valid_bearer(monkeypatch, authn, keys):
    priv_pem, _ = keys
    _oidc_settings(monkeypatch)
    monkeypatch.setattr(auth_mod, "_get_authenticator", lambda settings: authn)
    req = SimpleNamespace(headers={"Authorization": f"Bearer {_token(priv_pem)}"})
    user = get_current_user(req)
    assert user.username == "ivanov" and "sales" in user.roles


def test_oidc_mode_no_token_is_guest(monkeypatch, authn):
    _oidc_settings(monkeypatch)
    monkeypatch.setattr(auth_mod, "_get_authenticator", lambda settings: authn)
    user = get_current_user(SimpleNamespace(headers={}))
    assert user.roles == [GUEST]


def test_oidc_mode_ignores_spoofed_role_headers(monkeypatch, authn):
    _oidc_settings(monkeypatch)
    monkeypatch.setattr(auth_mod, "_get_authenticator", lambda settings: authn)
    user = get_current_user(
        SimpleNamespace(
            headers={
                "X-User": "service-account-aios-inviter",
                "X-User-Roles": "identity_provisioner",
            }
        )
    )
    assert user.roles == [GUEST] and user.username == "anonymous"


def test_oidc_mode_invalid_token_is_guest(monkeypatch, authn):
    _oidc_settings(monkeypatch)
    monkeypatch.setattr(auth_mod, "_get_authenticator", lambda settings: authn)
    req = SimpleNamespace(headers={"Authorization": "Bearer garbage"})
    user = get_current_user(req)
    assert user.roles == [GUEST]
