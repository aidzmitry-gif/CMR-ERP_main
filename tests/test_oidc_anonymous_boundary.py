"""Removing the proxy password must not expose unscoped system APIs."""
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from core.runtime import access
from core.services import auth


@pytest.mark.asyncio
@pytest.mark.parametrize("path", [
    "/system/modules", "/system/mdm/counterparties", "/approvals",
    "/docs", "/openapi.json", "/hr/me/profile", "/unregistered-module/data",
    "/system/access/extra", "/integrations-evil/data",
])
@pytest.mark.parametrize("headers", [{}, {"X-User-Roles": "director"},
                                    {"Authorization": "Bearer invalid"}])
async def test_guest_cannot_reach_system_or_unknown_routes(monkeypatch, path, headers):
    monkeypatch.setattr(access, "get_settings", lambda: SimpleNamespace(auth_mode="oidc"))
    monkeypatch.setattr(auth, "get_settings", lambda: SimpleNamespace(
        auth_mode="oidc", keycloak_issuer="", keycloak_audience="", keycloak_jwks_uri="",
    ))
    async def private(request):
        pytest.fail("anonymous request reached the private handler")
    app = Starlette(routes=[Route(path, private)])
    app.add_middleware(access.AccessControlMiddleware, prefixes=[])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get(path, headers=headers)).status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("path", [
    "/health", "/system/access", "/integrations/web/lead",
    "/telegram/webhook", "/marketing/seo/webhook",
])
async def test_machine_endpoints_keep_their_own_authentication(monkeypatch, path):
    monkeypatch.setattr(access, "get_settings", lambda: SimpleNamespace(auth_mode="oidc"))
    monkeypatch.setattr(auth, "get_current_user", lambda request: auth.CurrentUser(
        username="guest", roles=[auth.GUEST],
    ))
    async def machine_auth(request):
        return JSONResponse({"detail": "machine credential required"}, status_code=401)
    app = Starlette(routes=[Route(path, machine_auth, methods=["POST"])])
    app.add_middleware(access.AccessControlMiddleware, prefixes=[])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.post(path)).status_code == 401
