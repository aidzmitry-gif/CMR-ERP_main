"""Узкий Keycloak Admin API gateway для приглашения сотрудников.

Приложение использует service-account client, создаёт нового пользователя,
назначает одну realm-role и просит Keycloak отправить одноразовое письмо с действиями
``VERIFY_EMAIL`` + ``UPDATE_PASSWORD``. Пароль через CRM не проходит и не хранится.
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote, urlparse

import httpx

from config.access import ONBOARDING_ROLE


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


@dataclass(frozen=True)
class KeycloakActivation:
    user_id: str
    role: str


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
        self,
        *,
        username: str,
        full_name: str,
        email: str,
        expected_department: str,
        expected_role: str,
    ) -> KeycloakInvitation:
        if not self.configured:
            raise KeycloakAdminNotConfigured("keycloak_admin_not_configured")
        if not self._safe_redirect_uri():
            raise KeycloakAdminNotConfigured("keycloak_invite_redirect_uri_invalid")
        if self.lifespan < 300:
            raise KeycloakAdminNotConfigured("keycloak_invite_lifespan_too_short")

        try:
            if self._client is not None:
                return await self._invite(
                    self._client,
                    username=username,
                    full_name=full_name,
                    email=email,
                    expected_department=expected_department,
                    expected_role=expected_role,
                )
            async with httpx.AsyncClient(timeout=15.0) as client:
                return await self._invite(
                    client,
                    username=username,
                    full_name=full_name,
                    email=email,
                    expected_department=expected_department,
                    expected_role=expected_role,
                )
        except httpx.HTTPError as exc:
            raise KeycloakAdminError("keycloak_invite_transport_failed") from exc

    async def _invite(
        self,
        client: httpx.AsyncClient,
        *,
        username: str,
        full_name: str,
        email: str,
        expected_department: str,
        expected_role: str,
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
            expected_department=expected_department,
            expected_role=expected_role,
        )

        role_response = await client.get(
            f"{admin}/roles/{quote(ONBOARDING_ROLE, safe='')}", headers=headers
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
            role=ONBOARDING_ROLE,
            actions=self.ACTIONS,
            reused=reused,
        )

    async def stage_activation_target(
        self, *, user_id: str, expected_role: str
    ) -> KeycloakActivation:
        """Добавить будущую рабочую роль, не снимая ``onboarding``.

        Пока realm-role ``onboarding`` остаётся в токене, middleware приложения
        fail-closed и не пропускает бизнес-данные. Это позволяет сначала
        надёжно записать локальное pending-cleanup состояние.
        """

        if not self.configured:
            raise KeycloakAdminNotConfigured("keycloak_admin_not_configured")
        if not user_id or expected_role == ONBOARDING_ROLE:
            raise KeycloakAdminError("keycloak_activation_state_invalid")
        try:
            if self._client is not None:
                return await self._stage_activation_target(
                    self._client, user_id=user_id, expected_role=expected_role
                )
            async with httpx.AsyncClient(timeout=15.0) as client:
                return await self._stage_activation_target(
                    client, user_id=user_id, expected_role=expected_role
                )
        except httpx.HTTPError as exc:
            raise KeycloakAdminError("keycloak_activation_transport_failed") from exc

    async def _stage_activation_target(
        self, client: httpx.AsyncClient, *, user_id: str, expected_role: str
    ) -> KeycloakActivation:
        token = await self._service_token(client)
        headers = {"Authorization": f"Bearer {token}"}
        admin = f"{self.base_url}/admin/realms/{quote(self.realm, safe='')}"
        user_path = f"{admin}/users/{quote(user_id, safe='')}/role-mappings/realm"

        expected = await self._realm_role(client, admin, headers, expected_role)
        mapping_response = await client.post(user_path, headers=headers, json=[expected])
        self._expect(mapping_response, {204}, "keycloak_expected_role_assignment_failed")
        return KeycloakActivation(user_id=user_id, role=expected_role)

    async def remove_onboarding_role(self, *, user_id: str) -> None:
        """Финально снять onboarding после durable local pending-cleanup commit.

        Здесь принципиально нет автоматического rollback/retry: ошибка внешнего
        DELETE остаётся для ручной сверки, а вызывающий маршрут не выполняет
        дополнительную локальную запись после потенциально успешного DELETE.
        """

        if not self.configured:
            raise KeycloakAdminNotConfigured("keycloak_admin_not_configured")
        if not user_id:
            raise KeycloakAdminError("keycloak_activation_state_invalid")
        try:
            if self._client is not None:
                await self._remove_onboarding_role(self._client, user_id=user_id)
                return
            async with httpx.AsyncClient(timeout=15.0) as client:
                await self._remove_onboarding_role(client, user_id=user_id)
        except httpx.HTTPError as exc:
            raise KeycloakAdminError("keycloak_activation_cleanup_transport_failed") from exc

    async def _remove_onboarding_role(self, client: httpx.AsyncClient, *, user_id: str) -> None:
        token = await self._service_token(client)
        headers = {"Authorization": f"Bearer {token}"}
        admin = f"{self.base_url}/admin/realms/{quote(self.realm, safe='')}"
        onboarding = await self._realm_role(client, admin, headers, ONBOARDING_ROLE)
        response = await client.request(
            "DELETE",
            f"{admin}/users/{quote(user_id, safe='')}/role-mappings/realm",
            headers=headers,
            json=[onboarding],
        )
        self._expect(response, {204}, "keycloak_onboarding_role_remove_failed")

    async def _realm_role(
        self, client: httpx.AsyncClient, admin: str, headers: dict[str, str], name: str
    ) -> dict:
        response = await client.get(f"{admin}/roles/{quote(name, safe='')}", headers=headers)
        self._expect(response, {200}, "keycloak_role_lookup_failed")
        return response.json()

    def _safe_redirect_uri(self) -> bool:
        """Keycloak также обязан allowlist'ить URI, но CRM не принимает HTTP/opaque URI."""

        parsed = urlparse(self.redirect_uri)
        return (
            parsed.scheme == "https"
            and bool(parsed.netloc)
            and not parsed.username
            and not parsed.password
            and not parsed.fragment
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
        expected_department: str,
        expected_role: str,
    ) -> tuple[str, bool]:
        first_name, last_name = self._keycloak_names(full_name)
        user_payload = {
            "username": username,
            "email": email,
            "firstName": first_name,
            "lastName": last_name,
            "enabled": True,
            "emailVerified": False,
            # Это не рабочие атрибуты и не назначение роли: они только
            # фиксируют ожидание до явного решения руководителя.
            "attributes": {
                "access_state": ["onboarding"],
                "expected_department": [expected_department],
                "expected_role": [expected_role],
            },
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
        # Автоматический inviter не редактирует существующего Keycloak-пользователя:
        # нельзя молча добавить новую роль к старым правам или переслать письмо
        # неизвестному владельцу адреса. Сверка/повтор — отдельная ручная операция.
        raise KeycloakAdminConflict("keycloak_user_already_exists")

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
