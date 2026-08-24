"""Send one isolated Keycloak invitation and prove Mailpit received its link."""
from __future__ import annotations

import asyncio
import html
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.services.keycloak_admin import KeycloakAdminClient

EMAIL = "crm-git-001-invite@example.test"
LINK_RE = re.compile(r"https?://[^\s<>\"']+login-actions/action-token[^\s<>\"']+")


async def main() -> None:
    settings = SimpleNamespace(
        keycloak_admin_base_url="http://127.0.0.1:18080",
        keycloak_admin_realm="aios",
        keycloak_admin_client_id="crm-inviter",
        keycloak_admin_client_secret="crm-git-001-local-only",
        keycloak_invite_client_id="aios-backend",
        keycloak_invite_redirect_uri="http://127.0.0.1:19000/invitation-complete",
        keycloak_invite_lifespan_seconds=3600,
    )
    invitation = await KeycloakAdminClient(settings).invite_user(
        username="crm-git-001-invite",
        full_name="CRM GIT Local Invite",
        email=EMAIL,
        department="Продажи",
        role="sales",
    )

    async with httpx.AsyncClient(timeout=15.0) as client:
        message = None
        for _ in range(30):
            listing = await client.get("http://127.0.0.1:18025/api/v1/messages")
            listing.raise_for_status()
            candidates = [
                item for item in listing.json().get("messages", []) if EMAIL in str(item)
            ]
            if candidates:
                message_id = candidates[0]["ID"]
                detail = await client.get(
                    f"http://127.0.0.1:18025/api/v1/message/{message_id}"
                )
                detail.raise_for_status()
                payload = detail.json()
                message = html.unescape(
                    f"{payload.get('Text', '')}\n{payload.get('HTML', '')}"
                )
                break
            await asyncio.sleep(1)

    if message is None:
        raise RuntimeError("mailpit_message_missing")
    link_match = LINK_RE.search(message)
    if link_match is None:
        raise RuntimeError("keycloak_action_link_missing")

    print(f"invite_user_id={invitation.user_id}")
    print(f"invite_reused={str(invitation.reused).lower()}")
    print("mailpit_message_received=true")
    print("keycloak_action_link_present=true")


if __name__ == "__main__":
    asyncio.run(main())
