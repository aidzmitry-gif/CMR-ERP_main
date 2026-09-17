from __future__ import annotations

from types import SimpleNamespace

import pytest
from starlette.requests import Request
from starlette.responses import PlainTextResponse

from core.runtime import access


def request(path: str, headers=None) -> Request:
    raw_headers = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request({"type": "http", "method": "GET", "path": path, "headers": raw_headers})


def test_build_prefix_map_and_roles_delegate(monkeypatch):
    core = SimpleNamespace(routers=[
        SimpleNamespace(prefix="/sales", module="sales"),
        SimpleNamespace(prefix="/sales/deals", module="sales"),
        SimpleNamespace(prefix="", module="sales"),
        SimpleNamespace(prefix="/open", module="unknown"),
    ])
    assert access.build_prefix_map(core) == [
        ("/sales/deals", "sales"), ("/sales", "sales")
    ]
    monkeypatch.setattr("core.services.auth.get_current_user", lambda _request: SimpleNamespace(roles=["sales"]))
    assert access.roles_from_request(request("/sales")) == ["sales"]


@pytest.mark.asyncio
async def test_access_middleware_handles_open_onboarding_identity_and_module_paths(monkeypatch):
    async def call_next(_request):
        return PlainTextResponse("ok", status_code=200)

    middleware = access.AccessControlMiddleware(object(), prefixes=[("/sales", "sales")])
    monkeypatch.setattr(access, "is_package_allowed", lambda _package, roles: "sales" in roles)

    monkeypatch.setattr(access, "roles_from_request", lambda _request: ["employee"])
    assert (await middleware.dispatch(request("/health"), call_next)).status_code == 200
    assert (await middleware.dispatch(request("/ready"), call_next)).status_code == 200
    assert (await middleware.dispatch(request("/sales"), call_next)).status_code == 403
    assert (await middleware.dispatch(request("/other"), call_next)).status_code == 200

    monkeypatch.setattr(access, "roles_from_request", lambda _request: [access.ONBOARDING_ROLE, "sales"])
    assert (await middleware.dispatch(request("/sales"), call_next)).status_code == 403
    assert (await middleware.dispatch(request("/system/access"), call_next)).status_code == 200
    assert (await middleware.dispatch(request("/ready"), call_next)).status_code == 200

    monkeypatch.setattr(access, "roles_from_request", lambda _request: [access.IDENTITY_PROVISIONER_ROLE])
    assert (await middleware.dispatch(request("/sales"), call_next)).status_code == 403
    assert (await middleware.dispatch(request("/system/users/preflight"), call_next)).status_code == 200
    assert (await middleware.dispatch(request("/ready"), call_next)).status_code == 200
