"""Identity / RBAC / MFA через Keycloak. Заглушка до части 5.

В части 5 — интеграция с Keycloak (OIDC), проверка прав по RBAC, MFA и
неизменяемый audit log. Ставится до интеграции с 1С (часть 6).
"""
from __future__ import annotations


class AuthService:
    """Заглушка сервиса аутентификации/авторизации."""

    def __init__(self) -> None:
        self.provider = "keycloak (часть 5)"
