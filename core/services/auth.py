"""Лёгкий RBAC (dev) — без Keycloak. Реальный OIDC/MFA подключается позже (часть 5).

Текущий пользователь определяется заголовками ``X-User`` / ``X-User-Roles``
(dev-режим). Fail-closed (SECURITY.md P0-1): без заголовка ролей — бесправный
«Гость», НЕ «Админ». Права берутся из ролей, объявленных модулями (``Core.roles``).
"""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request


@dataclass
class CurrentUser:
    username: str
    roles: list[str]


class AuthService:
    """Заглушка identity-сервиса. Реальный Keycloak (OIDC/MFA) — позже."""

    provider = "dev (Keycloak — часть 5, позже)"


def get_current_user(request: Request) -> CurrentUser:
    """Определить пользователя из заголовков (dev). По умолчанию — бесправный «Гость».

    Fail-closed (SECURITY.md P0-1): без заголовка роли больше НЕ выдаём «Админ».
    «Гость» не входит в матрицу доступа и в супер-роли → видит только публичные/
    системные роуты, на защищённые модули получает 403. Настоящая аутентификация
    (Keycloak OIDC) заменит этот заголовок проверенным токеном в P1 (часть 5).
    """
    roles_header = request.headers.get("X-User-Roles")
    username = request.headers.get("X-User", "anonymous")
    roles = [r.strip() for r in roles_header.split(",") if r.strip()] if roles_header else ["Гость"]
    return CurrentUser(username=username, roles=roles or ["Гость"])


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
