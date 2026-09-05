"""Contract for DB-backed effective access of linked OIDC identities."""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from core.domain.models import User
from core.runtime.app import create_app
from core.services import auth as auth_mod
from core.services.auth import (
    GUEST,
    CurrentUser,
    EffectiveIdentityLookupError,
    resolve_effective_oidc_user,
)


@pytest.mark.asyncio
async def test_linked_user_old_jwt_role_is_denied_after_downgrade(session):
    session.add(
        User(
            username="manager",
            full_name="Manager",
            keycloak_user_id="kc-manager",
            role="sales",
            status="active",
        )
    )
    await session.commit()

    effective = await resolve_effective_oidc_user(
        CurrentUser("manager", ["sales_head"], "kc-manager"), session
    )

    assert effective.roles == [GUEST]


@pytest.mark.asyncio
async def test_linked_onboarding_wins_over_mixed_signed_token(session):
    session.add(
        User(
            username="new-user",
            full_name="New User",
            keycloak_user_id="kc-new-user",
            role="onboarding",
            status="onboarding",
        )
    )
    await session.commit()

    effective = await resolve_effective_oidc_user(
        CurrentUser("new-user", ["onboarding", "sales_head", "director"], "kc-new-user"),
        session,
    )

    assert effective.roles == ["onboarding"]


@pytest.mark.asyncio
async def test_onboarding_claim_stays_fail_closed_during_active_local_transition(session):
    session.add(
        User(
            username="transition-user",
            full_name="Transition User",
            keycloak_user_id="kc-transition-user",
            role="sales",
            status="active",
        )
    )
    await session.commit()

    effective = await resolve_effective_oidc_user(
        CurrentUser("transition-user", ["onboarding", "sales"], "kc-transition-user"),
        session,
    )

    assert effective.roles == ["onboarding"]


@pytest.mark.asyncio
async def test_unlinked_director_keeps_verified_claims(session):
    claimed = CurrentUser("legacy-director", ["director"], "kc-legacy-director")

    assert await resolve_effective_oidc_user(claimed, session) == claimed


@pytest.mark.asyncio
async def test_identity_lookup_failure_is_explicit_and_contains_no_database_details(session):
    await session.execute(text("DROP TABLE app_user"))

    with pytest.raises(EffectiveIdentityLookupError) as exc_info:
        await resolve_effective_oidc_user(CurrentUser("user", ["sales"], "kc-user"), session)

    assert str(exc_info.value) == "effective_identity_lookup_failed"


async def _effective_access_client(session, monkeypatch, claimed: CurrentUser):
    """App-level middleware harness backed by the test database factory."""
    app = create_app()
    assert session.bind is not None
    app.state.core.services.db.session_factory = async_sessionmaker(
        session.bind, expire_on_commit=False
    )

    def _current_user(request):
        return getattr(request.state, "effective_current_user", claimed)

    monkeypatch.setattr(auth_mod, "get_current_user", _current_user)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_middleware_exposes_current_local_role_and_denies_old_crm_jwt(session, monkeypatch):
    session.add(
        User(
            username="crm-user",
            full_name="CRM User",
            keycloak_user_id="kc-crm-user",
            role="sales",
            status="active",
        )
    )
    await session.commit()
    client = await _effective_access_client(
        session, monkeypatch, CurrentUser("crm-user", ["sales_head"], "kc-crm-user")
    )
    async with client:
        access = await client.get("/system/access")
        crm = await client.get("/sales/ping")
        system = await client.get("/system/modules")

    assert access.status_code == 200
    assert access.json()["current_roles"] == [GUEST]
    assert crm.status_code == 403
    assert system.status_code == 403


@pytest.mark.asyncio
async def test_middleware_allows_only_sanitized_access_page_for_linked_transition_state(
    session, monkeypatch
):
    session.add(
        User(
            username="changing-user",
            full_name="Changing User",
            keycloak_user_id="kc-changing-user",
            role="sales",
            status="role_changing",
        )
    )
    await session.commit()
    client = await _effective_access_client(
        session, monkeypatch, CurrentUser("changing-user", ["sales"], "kc-changing-user")
    )
    async with client:
        access = await client.get("/system/access")
        system = await client.get("/system/modules")
        crm = await client.get("/sales/ping")

    assert access.status_code == 200
    assert access.json()["current_roles"] == [GUEST]
    assert system.status_code == 403
    assert crm.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["sales", "sales_head", "sales_cli"])
async def test_own_visibility_blocks_neighbor_deal_surfaces_with_same_signed_token(
    session, monkeypatch, role
):
    user = User(
        username="crm-owner", full_name="CRM Owner", keycloak_user_id="kc-owner",
        role=role, status="active", deal_visibility="all", employee_id=100,
    )
    session.add(user)
    await session.commit()
    claimed = CurrentUser("crm-owner", [role], "kc-owner")
    client = await _effective_access_client(session, monkeypatch, claimed)
    async with client:
        # Unknown paths pass the all-mode gate and reach routing (404), not a
        # real unscoped handler or database. Keep the exact same JWT identity.
        for prefix in ("/leads", "/service", "/system/mdm/counterparty"):
            before = await client.get(prefix + "/__scope_probe__/missing")
            assert before.status_code == 404
        user.deal_visibility = "own"
        await session.commit()
        effective = await resolve_effective_oidc_user(claimed, session)
        assert effective.roles == [role]
        assert effective.deal_visibility == "own"
        for method, path in (
            ("GET", "/leads"), ("GET", "/leads/1"),
            ("POST", "/leads/1/convert"),
            ("GET", "/service/requests"), ("PATCH", "/service/requests/1"),
            ("GET", "/system/mdm/counterparty/1"),
            ("GET", "/system/mdm/counterparty/1/"),
        ):
            result = await client.request(method, path)
            assert result.status_code == 403, (method, path, result.text)
        assert (await client.get("/system/access")).json()["current_roles"] == [role]
        assert (await client.get("/sales/ping")).status_code == 200
        # Shared catalog prefixes and near-matching names must not be blocked.
        for path in (
            "/system/references/__scope_probe__/missing",
            "/system/sku/__scope_probe__/missing",
            "/system/tnved/lookup/__scope_probe__/missing",
            "/leads-other/__scope_probe__",
        ):
            assert (await client.get(path)).status_code == 404
        user.deal_visibility = "all"
        await session.commit()
        assert (await client.get("/leads/__scope_probe__/missing")).status_code == 404
