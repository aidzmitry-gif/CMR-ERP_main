"""Provision an isolated Keycloak realm for CRM-GIT-001 acceptance.

All credentials and endpoints are disposable test-only values.  The script is
idempotent so the preserved Docker volume can be reused without deletion.
"""
from __future__ import annotations

import asyncio
import sys

import httpx

BASE_URL = "http://127.0.0.1:18080"
REALM = "aios"
LOGIN_CLIENT = "aios-backend"
ADMIN_CLIENT = "crm-inviter"
ADMIN_SECRET = "crm-git-001-local-only"
REDIRECT_URI = "http://127.0.0.1:19000/invitation-complete"


async def wait_for_keycloak(client: httpx.AsyncClient) -> None:
    for _ in range(90):
        try:
            response = await client.get(f"{BASE_URL}/realms/master")
            if response.status_code == 200:
                return
        except httpx.HTTPError:
            pass
        await asyncio.sleep(2)
    raise RuntimeError("keycloak_not_ready")


async def main() -> None:
    async with httpx.AsyncClient(timeout=20.0) as client:
        await wait_for_keycloak(client)
        token_response = await client.post(
            f"{BASE_URL}/realms/master/protocol/openid-connect/token",
            data={
                "grant_type": "password",
                "client_id": "admin-cli",
                "username": "admin",
                "password": "admin",
            },
        )
        token_response.raise_for_status()
        headers = {"Authorization": f"Bearer {token_response.json()['access_token']}"}

        realm_payload = {
            "realm": REALM,
            "enabled": True,
            "displayName": "AI-OS local acceptance",
            "smtpServer": {
                "host": "mailpit",
                "port": "1025",
                "from": "no-reply@aios.local",
                "fromDisplayName": "AI-OS",
                "auth": "false",
                "starttls": "false",
                "ssl": "false",
            },
        }
        create_realm = await client.post(
            f"{BASE_URL}/admin/realms", headers=headers, json=realm_payload
        )
        if create_realm.status_code == 409:
            update_realm = await client.put(
                f"{BASE_URL}/admin/realms/{REALM}", headers=headers, json=realm_payload
            )
            update_realm.raise_for_status()
        else:
            create_realm.raise_for_status()

        async def ensure_client(client_id: str, payload: dict) -> str:
            found = await client.get(
                f"{BASE_URL}/admin/realms/{REALM}/clients",
                headers=headers,
                params={"clientId": client_id},
            )
            found.raise_for_status()
            matches = found.json()
            if matches:
                internal_id = matches[0]["id"]
                update = await client.put(
                    f"{BASE_URL}/admin/realms/{REALM}/clients/{internal_id}",
                    headers=headers,
                    json={**payload, "id": internal_id},
                )
                update.raise_for_status()
                return internal_id
            created = await client.post(
                f"{BASE_URL}/admin/realms/{REALM}/clients",
                headers=headers,
                json=payload,
            )
            created.raise_for_status()
            return created.headers["location"].rstrip("/").rsplit("/", 1)[-1]

        await ensure_client(
            LOGIN_CLIENT,
            {
                "clientId": LOGIN_CLIENT,
                "enabled": True,
                "publicClient": True,
                "standardFlowEnabled": True,
                "directAccessGrantsEnabled": True,
                "redirectUris": [REDIRECT_URI],
                "webOrigins": ["http://127.0.0.1:19000"],
            },
        )
        admin_internal_id = await ensure_client(
            ADMIN_CLIENT,
            {
                "clientId": ADMIN_CLIENT,
                "enabled": True,
                "publicClient": False,
                "secret": ADMIN_SECRET,
                "serviceAccountsEnabled": True,
                "standardFlowEnabled": False,
                "directAccessGrantsEnabled": False,
            },
        )

        role = await client.post(
            f"{BASE_URL}/admin/realms/{REALM}/roles",
            headers=headers,
            json={"name": "sales", "description": "Local acceptance sales role"},
        )
        if role.status_code not in {201, 409}:
            role.raise_for_status()

        service_user = await client.get(
            f"{BASE_URL}/admin/realms/{REALM}/clients/{admin_internal_id}/service-account-user",
            headers=headers,
        )
        service_user.raise_for_status()
        service_user_id = service_user.json()["id"]

        realm_management = await client.get(
            f"{BASE_URL}/admin/realms/{REALM}/clients",
            headers=headers,
            params={"clientId": "realm-management"},
        )
        realm_management.raise_for_status()
        realm_management_id = realm_management.json()[0]["id"]
        realm_admin = await client.get(
            f"{BASE_URL}/admin/realms/{REALM}/clients/{realm_management_id}/roles/realm-admin",
            headers=headers,
        )
        realm_admin.raise_for_status()
        mapping = await client.post(
            f"{BASE_URL}/admin/realms/{REALM}/users/{service_user_id}"
            f"/role-mappings/clients/{realm_management_id}",
            headers=headers,
            json=[realm_admin.json()],
        )
        if mapping.status_code != 204:
            mapping.raise_for_status()

    print("keycloak_mailpit_provisioned")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        print(f"provision_failed:{type(exc).__name__}:{exc}", file=sys.stderr)
        raise
