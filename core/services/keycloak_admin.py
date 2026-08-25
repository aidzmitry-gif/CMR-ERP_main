"""Узкий Keycloak Admin API gateway для приглашения сотрудников.

Приложение использует service-account client, создаёт/переиспользует пользователя,
назначает одну realm-role и просит Keycloak отправить одноразовое письмо с действиями
``VERIFY_EMAIL`` + ``UPDATE_PASSWORD``. Пароль через CRM не проходит и не хранится.
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

import httpx


class KeycloakAdminError(RuntimeError):
    """Безопасная ошибка upstream без тела ответа и секретов."""

    def __init__(self, code: str, *, upstream_status: int | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.upstream_status = upstream_status


class KeycloakAdminNotConfigured(KeycloakAdminError):
    pass


class KeycloakAdminConflict(KeycloakAdminError):
    pass


@dataclass(frozen=True)
class KeycloakInvitation:
    user_id: str
    username: str
    email: str
    role: str
    actions: tuple[str, ...]
    reused: bool


class KeycloakAdminClient:
    """Минимальный async-клиент Admin REST; injectable ``httpx`` для тестов."""

    ACTIONS = ("VERIFY_EMAIL", "UPDATE_PASSWORD")

    def __init__(self, settings, *, client: httpx.AsyncClient | None = None) -> None:
        self.base_url = settings.keycloak_admin_base_url.rstrip("/")
        self.realm = settings.keycloak_admin_realm.strip()
        self.admin_client_id = settings.keycloak_admin_client_id.strip()
        self.admin_client_secret = settings.keycloak_admin_client_secret
        self.invite_client_id = settings.keycloak_invite_client_id.strip()
        self.redirect_uri = settings.keycloak_invite_redirect_uri.strip()
        self.lifespan = settings.keycloak_invite_lifespan_seconds
        self._client = client

    @property
    def configured(self) -> bool:
        return all(
            (
                self.base_url,
                self.realm,
                self.admin_client_id,
                self.admin_client_secret,
                self.invite_client_id,
                self.redirect_uri,
            )
        )

    async def invite_user(
        self, *, username: str, full_name: str, email: str, department: str, role: str
    ) -> KeycloakInvitation:
        if not self.configured:
            raise KeycloakAdminNotConfigured("keycloak_admin_not_configured")
        if self.lifespan < 300:
            raise KeycloakAdminNotConfigured("keycloak_invite_lifespan_too_short")

        if self._client is not None:
            return await self._invite(
                self._client,
                username=username,
                full_name=full_name,
                email=email,
                department=department,
                role=role,
            )
        async with httpx.AsyncClient(timeout=15.0) as client:
            return await self._invite(
                client,
                username=username,
                full_name=full_name,
                email=email,
                department=department,
                role=role,
            )

    async def _invite(
        self,
        client: httpx.AsyncClient,
        *,
        username: str,
        full_name: str,
        email: str,
        department: str,
        role: str,
    ) -> KeycloakInvitation:
        token = await self._service_token(client)
        headers = {"Authorization": f"Bearer {token}"}
        admin = f"{self.base_url}/admin/realms/{quote(self.realm, safe='')}"

        user_id, reused = await self._ensure_user(
            client,
            admin=admin,
            headers=headers,
            username=username,
            full_name=full_name,
            email=email,
            department=department,
        )

        role_response = await client.get(
            f"{admin}/roles/{quote(role, safe='')}", headers=headers
        )
        self._expect(role_response, {200}, "keycloak_role_lookup_failed")
        role_representation = role_response.json()
        mapping_response = await client.post(
            f"{admin}/users/{quote(user_id, safe='')}/role-mappings/realm",
            headers=headers,
            json=[role_representation],
        )
        self._expect(mapping_response, {204}, "keycloak_role_assignment_failed")

        action_response = await client.put(
            f"{admin}/users/{quote(user_id, safe='')}/execute-actions-email",
            headers=headers,
            params={
                "client_id": self.invite_client_id,
                "redirect_uri": self.redirect_uri,
                "lifespan": str(self.lifespan),
            },
            json=list(self.ACTIONS),
        )
        self._expect(action_response, {204}, "keycloak_invite_email_failed")
        return KeycloakInvitation(
            user_id=user_id,
            username=username,
            email=email,
            role=role,
            actions=self.ACTIONS,
            reused=reused,
        )

    async def _service_token(self, client: httpx.AsyncClient) -> str:
        response = await client.post(
            f"{self.base_url}/realms/{quote(self.realm, safe='')}/protocol/openid-connect/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self.admin_client_id,
                "client_secret": self.admin_client_secret,
            },
        )
        self._expect(response, {200}, "keycloak_admin_token_failed")
        token = response.json().get("access_token")
        if not token:
            raise KeycloakAdminError("keycloak_admin_token_missing")
        return str(token)

    async def _ensure_user(
        self,
        client: httpx.AsyncClient,
        *,
        admin: str,
        headers: dict[str, str],
        username: str,
        full_name: str,
        email: str,
        department: str,
    ) -> tuple[str, bool]:
        first_name, last_name = self._keycloak_names(full_name)
        user_payload = {
            "username": username,
            "email": email,
            "firstName": first_name,
            "lastName": last_name,
            "enabled": True,
            "emailVerified": False,
            "attributes": {"department": [department]},
            "requiredActions": list(self.ACTIONS),
        }
        response = await client.post(
            f"{admin}/users",
            headers=headers,
            json=user_payload,
        )
        if response.status_code == 201:
            location = response.headers.get("location", "").rstrip("/")
            user_id = location.rsplit("/", 1)[-1]
            if not user_id or user_id == "users":
                raise KeycloakAdminError("keycloak_created_user_id_missing")
            return user_id, False
        if response.status_code != 409:
            self._expect(response, {201}, "keycloak_user_create_failed")

        lookup = await client.get(
            f"{admin}/users",
            headers=headers,
            params={"username": username, "exact": "true"},
        )
        self._expect(lookup, {200}, "keycloak_user_lookup_failed")
        matches = [u for u in lookup.json() if u.get("username") == username]
        if len(matches) != 1:
            raise KeycloakAdminConflict("keycloak_username_conflict")
        existing = matches[0]
        if str(existing.get("email", "")).lower() != email.lower():
            raise KeycloakAdminConflict("keycloak_username_email_conflict")
        user_id = str(existing.get("id", ""))
        if not user_id:
            raise KeycloakAdminError("keycloak_existing_user_id_missing")
        update = await client.put(
            f"{admin}/users/{quote(user_id, safe='')}",
            headers=headers,
            json=user_payload,
        )
        self._expect(update, {204}, "keycloak_user_update_failed")
        return user_id, True

    @staticmethod
    def _keycloak_names(full_name: str) -> tuple[str, str]:
        """Map conventional RU `Фамилия Имя ...` to required Keycloak fields."""
        parts = full_name.strip().split(maxsplit=1)
        if len(parts) == 2:
            return parts[1], parts[0]
        value = parts[0] if parts else "Сотрудник"
        return value, value

    @staticmethod
    def _expect(response: httpx.Response, allowed: set[int], code: str) -> None:
        if response.status_code not in allowed:
            raise KeycloakAdminError(code, upstream_status=response.status_code)
