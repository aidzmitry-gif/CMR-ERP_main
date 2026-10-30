"""Synthetic scope checks; no real grants, configuration writes, or database."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from core.runtime.deps import get_core, get_session
from core.runtime.system_routes import router
from core.services.auth import GUEST, CurrentUser, get_current_user
from core.services.instance_organization import resolve_instance_organization

UNP = "987654321"
ORG = {"id": 7, "name": "Synthetic organization", "unp": UNP}
USER = CurrentUser(username="synthetic-reader", roles=["seller"])


def gateway(rows):
    return SimpleNamespace(source_organizations=AsyncMock(return_value=rows))


async def test_exact_configured_organization_not_first_available():
    source = gateway([dict(ORG, id=8, unp="111111111"), ORG])
    assert await resolve_instance_organization(None, USER, source, UNP) == {
        "organization": ORG, "configuration": "AIOS_SELLER_UNP",
    }
    source.source_organizations.assert_awaited_once_with(None, USER)


@pytest.mark.parametrize("unp", ["", "123", "９８７６５４３２１"])
async def test_invalid_configuration_never_selects_an_available_book(unp):
    source = gateway([ORG])
    with pytest.raises(HTTPException) as exc:
        await resolve_instance_organization(None, USER, source, unp)
    assert exc.value.status_code == 503
    source.source_organizations.assert_not_awaited()


async def test_missing_facade_is_unavailable():
    with pytest.raises(HTTPException) as exc:
        await resolve_instance_organization(None, USER, None, UNP)
    assert exc.value.status_code == 503


async def test_access_does_not_fallback_to_the_only_other_organization():
    with pytest.raises(HTTPException) as exc:
        await resolve_instance_organization(None, USER, gateway([dict(ORG, unp="111111111")]), UNP)
    assert exc.value.status_code == 403


async def test_duplicate_binding_stops_before_selection():
    with pytest.raises(HTTPException) as exc:
        await resolve_instance_organization(None, USER, gateway([ORG, dict(ORG, id=9)]), UNP)
    assert exc.value.status_code == 409


async def test_guest_cannot_read_installation_identity():
    source = gateway([ORG])
    with pytest.raises(HTTPException) as exc:
        await resolve_instance_organization(None, CurrentUser(GUEST, [GUEST]), source, UNP)
    assert exc.value.status_code == 401
    source.source_organizations.assert_not_awaited()


@pytest.mark.parametrize("explicit, expected", [(True, 200), (False, 503)])
async def test_http_context_uses_only_explicit_server_setting(explicit, expected):
    app = FastAPI()
    app.include_router(router)
    source = gateway([ORG])
    config = SimpleNamespace(seller_unp=UNP, model_fields_set={"seller_unp"} if explicit else set())
    app.dependency_overrides[get_core] = lambda: SimpleNamespace(
        config=config, services=SimpleNamespace(accounting=source),
    )
    app.dependency_overrides[get_current_user] = lambda: USER

    async def unused_session():
        yield SimpleNamespace(get=AsyncMock(return_value=None))

    app.dependency_overrides[get_session] = unused_session
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://synthetic") as client:
        response = await client.get("/system/instance-organization")
    assert response.status_code == expected
    if explicit:
        assert response.json()["organization"] == ORG
    else:
        source.source_organizations.assert_not_awaited()
