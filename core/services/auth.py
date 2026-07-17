"""RBAC + AuthN. Dev доверяет заголовкам, oidc — проверенному Keycloak-JWT.

Текущий пользователь определяется по ``settings.auth_mode``:
- ``dev`` (по умолчанию) — заголовки ``X-User`` / ``X-User-Roles`` (без проверки подписи).
- ``oidc`` — Bearer-JWT Keycloak: подпись (RS256 по JWKS realm'а), ``iss``/``aud``/``exp``;
  роли из claim ``realm_access.roles``.

Fail-closed (SECURITY.md P0-1/P1): без заголовка ИЛИ без валидного токена — бесправный
«Гость», НЕ «Админ». Права берутся из ролей, объявленных модулями (``Core.roles``).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request

from core.services.config import get_settings

logger = logging.getLogger("aios.auth")

GUEST = "Гость"


@dataclass
class CurrentUser:
    username: str
    roles: list[str]


class OidcAuthenticator:
    """Проверка Bearer-JWT Keycloak: подпись (RS256 по JWKS) + ``iss``/``aud``/``exp``.

    Ключ подписи берётся из JWKS realm'а (кэшируется ``PyJWKClient``; сеть — только при
    первом токене). ``validate`` fail-closed: любая ошибка (просрочка, чужой aud/iss,
    кривой токен, недоступный JWKS) → ``None``, а вызывающий код выдаёт «Гостя».
    """

    def __init__(self, issuer: str, audience: str, jwks_uri: str = "") -> None:
        self.issuer = issuer.rstrip("/")
        self.audience = audience
        self.jwks_uri = (jwks_uri or f"{self.issuer}/protocol/openid-connect/certs").rstrip("/")
        self._jwk_client = None

    def _signing_key(self, token: str):
        if self._jwk_client is None:
            from jwt import PyJWKClient

            self._jwk_client = PyJWKClient(self.jwks_uri)
        return self._jwk_client.get_signing_key_from_jwt(token).key

    def validate(self, token: str) -> CurrentUser | None:
        import jwt

        try:
            claims = jwt.decode(
                token,
                self._signing_key(token),
                algorithms=["RS256"],
                issuer=self.issuer,
                audience=self.audience,  # пусто → реальный токен не пройдёт (fail-closed)
                leeway=30,  # допуск на рассинхрон часов app ↔ Keycloak
                options={"require": ["exp", "iss", "aud"]},
            )
        except jwt.InvalidTokenError as exc:
            logger.warning("OIDC: токен отклонён (%s)", type(exc).__name__)
            return None
        except Exception as exc:  # JWKS недоступен / неизвестный kid — тоже fail-closed, но логируем
            logger.warning("OIDC: ошибка валидации (%s)", type(exc).__name__)
            return None
        username = claims.get("preferred_username") or claims.get("sub") or "oidc-user"
        roles = [r for r in (claims.get("realm_access") or {}).get("roles", []) if r]
        return CurrentUser(username=username, roles=roles or [GUEST])


class AuthService:
    """Identity-сервис. dev — доверие заголовкам; oidc — проверенный Keycloak-JWT (см. модуль)."""

    provider = "dev/oidc (Keycloak — за auth_mode)"


_authenticator: OidcAuthenticator | None = None


def _get_authenticator(settings) -> OidcAuthenticator | None:
    """Ленивый singleton OIDC-аутентификатора (пересоздаётся при смене issuer/jwks)."""
    global _authenticator
    issuer = settings.keycloak_issuer.rstrip("/")
    if not issuer:
        return None
    jwks = (getattr(settings, "keycloak_jwks_uri", None) or "").rstrip("/")
    if (
        _authenticator is None
        or _authenticator.issuer != issuer
        or _authenticator.audience != settings.keycloak_audience
        or _authenticator.jwks_uri
        != (jwks or f"{issuer}/protocol/openid-connect/certs")
    ):
        _authenticator = OidcAuthenticator(issuer, settings.keycloak_audience, jwks)
    return _authenticator


def _bearer_token(request: Request) -> str | None:
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip() or None
    return None


def _roles_from_header(request: Request) -> CurrentUser:
    roles_header = request.headers.get("X-User-Roles")
    username = request.headers.get("X-User", "anonymous")
    roles = [r.strip() for r in roles_header.split(",") if r.strip()] if roles_header else [GUEST]
    return CurrentUser(username=username, roles=roles or [GUEST])


def get_current_user(request: Request) -> CurrentUser:
    """Текущий пользователь по ``settings.auth_mode`` (dev=заголовок, oidc=JWT). Fail-closed «Гость».

    Fail-closed (SECURITY.md P0-1/P1): без заголовка/валидного токена — бесправный «Гость»,
    видит только публичные/системные роуты, на защищённые модули получает 403.
    """
    settings = get_settings()
    if settings.auth_mode == "oidc":
        token = _bearer_token(request)
        auth = _get_authenticator(settings)
        user = auth.validate(token) if (auth and token) else None
        return user or CurrentUser(username="anonymous", roles=[GUEST])
    return _roles_from_header(request)


def has_permission(core, user: CurrentUser, permission: str) -> bool:
    """Есть ли у пользователя право.

    Супер-роли (``config.access.SUPER_ROLES``: Админ/Директор/Коммерческий) имеют все
    права — единый источник истины с матрицей доступа к модулям, чтобы две системы
    (модульный доступ и право на действие) не расходились. Прочие роли получают права
    из ролей, объявленных модулями (``core.roles``).
    """
    from config.access import is_super

    if is_super(user.roles):
        return True
    granted: set[str] = set()
    for role in core.roles:
        if role.name in user.roles:
            granted.update(role.permissions)
    return permission in granted


def require_permission(permission: str):
    """FastAPI-зависимость: пропустить только при наличии права, иначе 403."""

    def checker(request: Request, user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not has_permission(request.app.state.core, user, permission):
            raise HTTPException(status_code=403, detail=f"Недостаточно прав: {permission}")
        return user

    return checker
