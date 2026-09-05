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
from typing import TYPE_CHECKING

from fastapi import Depends, HTTPException, Request

from core.services.config import get_settings

logger = logging.getLogger("aios.auth")

GUEST = "Гость"

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class CurrentUser:
    username: str
    roles: list[str]
    # ``sub`` is the stable Keycloak subject.  It is intentionally distinct
    # from ``preferred_username``: a username can be renamed, while app_user
    # binds a managed employee to this immutable identity.
    keycloak_user_id: str | None = None
    # Set only after a successful app_user lookup.  Middleware uses it to keep
    # suspended/transitioning linked accounts out of otherwise open system
    # endpoints, while still rendering their sanitized access page.
    local_status: str | None = None
    # Read from the local account on each request; never from JWT/client input.
    deal_visibility: str | None = None


class EffectiveIdentityLookupError(RuntimeError):
    """The local identity check was unavailable; callers must fail closed."""


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
                options={"require": ["exp", "iss", "aud", "sub"]},
            )
        except jwt.InvalidTokenError as exc:
            logger.warning("OIDC: токен отклонён (%s)", type(exc).__name__)
            return None
        except Exception as exc:  # JWKS недоступен / неизвестный kid — тоже fail-closed, но логируем
            logger.warning("OIDC: ошибка валидации (%s)", type(exc).__name__)
            return None
        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject.strip():
            logger.warning("OIDC: токен отклонён (invalid_sub)")
            return None
        subject = subject.strip()
        username = claims.get("preferred_username") or subject or "oidc-user"
        roles = [r for r in (claims.get("realm_access") or {}).get("roles", []) if r]
        return CurrentUser(
            username=str(username),
            roles=roles or [GUEST],
            keycloak_user_id=subject,
        )


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


async def resolve_effective_oidc_user(
    user: CurrentUser, session: "AsyncSession"
) -> CurrentUser:
    """Constrain a linked Keycloak subject to its current local access state.

    Users not managed in ``app_user`` deliberately retain their verified OIDC
    claims.  This keeps the existing unlinked director/commercial accounts
    working while making a locally managed employee's current role and status
    authoritative on every protected request.
    """
    if not user.keycloak_user_id:
        return user

    try:
        from sqlalchemy import select

        from config.access import ONBOARDING_ROLE
        from core.domain.models import User

        linked = (
            await session.execute(
                select(User).where(User.keycloak_user_id == user.keycloak_user_id)
            )
        ).scalar_one_or_none()
    except Exception as exc:
        raise EffectiveIdentityLookupError("effective_identity_lookup_failed") from exc

    if linked is None:
        return user
    if linked.status != "active" and linked.status != "onboarding":
        return CurrentUser(
            user.username, [GUEST], user.keycloak_user_id, linked.status or "unknown"
        )
    # Claim presence remains fail-closed even if a concurrent local update has
    # already marked the row active: Keycloak has not yet removed onboarding,
    # so this token cannot open business data.
    if ONBOARDING_ROLE in user.roles or linked.status == "onboarding":
        return CurrentUser(user.username, [ONBOARDING_ROLE], user.keycloak_user_id, linked.status)
    if linked.status == "active" and linked.role and linked.role in user.roles:
        # Never elevate a signed token from a local row: the current persisted
        # role must also be present in this token.  A stale/contaminated token
        # therefore loses access instead of retaining a former extra role.
        return CurrentUser(
            user.username, [linked.role], user.keycloak_user_id, linked.status,
            deal_visibility=linked.deal_visibility,
        )
    return CurrentUser(user.username, [GUEST], user.keycloak_user_id, linked.status)


def get_current_user(request: Request) -> CurrentUser:
    """Текущий пользователь по ``settings.auth_mode`` (dev=заголовок, oidc=JWT). Fail-closed «Гость».

    Fail-closed (SECURITY.md P0-1/P1): без заголовка/валидного токена — бесправный «Гость»,
    видит только публичные/системные роуты, на защищённые модули получает 403.
    """
    effective = getattr(getattr(request, "state", None), "effective_current_user", None)
    if isinstance(effective, CurrentUser):
        return effective

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
    from config.access import (
        IDENTITY_PROVISIONER_PERMISSIONS,
        IDENTITY_PROVISIONER_ROLE,
        is_super,
    )

    if is_super(user.roles):
        return True
    if IDENTITY_PROVISIONER_ROLE in user.roles:
        return permission in IDENTITY_PROVISIONER_PERMISSIONS
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
