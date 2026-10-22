"""Contract for DB-backed effective access of linked OIDC identities."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from core.domain.models import AuditLog, User
from core.runtime.app import create_app
from core.services import auth as auth_mod
from core.services.auth import (
    GUEST,
    CurrentUser,
    EffectiveIdentityLookupError,
    resolve_effective_oidc_user,
)


@pytest.mark.parametrize("changes", [{"status": "suspended"}, {"role": "guest"}])
async def test_effective_identity_refreshes_a_retained_user(session, changes):
    linked = User(username="retained-user", full_name="Synthetic", keycloak_user_id="kc-retained",
                  role="director", status="active")
    session.add(linked)
    await session.commit()
    principal = CurrentUser("retained-user", ["director"], "kc-retained")
    assert (await resolve_effective_oidc_user(principal, session)).roles == ["director"]
    # A database change must be seen even while this session retains the old ORM row.
    await session.execute(update(User).where(User.id == linked.id).values(**changes)
                          .execution_options(synchronize_session=False))
    assert linked.status == "active" and linked.role == "director"
    assert (await resolve_effective_oidc_user(principal, session)).roles == [GUEST]


@pytest.mark.asyncio
async def test_named_dev_identity_applies_persisted_scope_before_all_module_gates(api, session):
    session.add(User(username="dev-own", full_name="Synthetic own", employee_id=654,
                     role="sales", status="active", deal_visibility="own"))
    await session.commit()
    headers = {"X-User": "dev-own", "X-User-Roles": "sales"}
    assert (await api.get('/sales/clients', headers={'X-User-Roles':'sales'})).status_code == 403
    assert (await api.get('/sales/clients', headers=headers)).status_code == 200
    leads = await api.get('/leads', headers=headers)
    assert leads.status_code == 200 and leads.json() == []
    assert leads.headers['X-CRM-Visibility'] == 'own'
    for path in ['/leads/plan', '/service/tickets', '/system/mdm/counterparty']:
        assert (await api.get(path, headers=headers)).status_code == 403
    assert (await api.get('/sales/clients', headers={**headers, 'X-User-Roles':'director'})).status_code == 403
    assert (await api.get('/sales/clients', headers={**headers, 'X-User':'unknown-dev'})).status_code == 403
    assert (await api.get('/sales/clients', headers={'X-User':'unlinked-director', 'X-User-Roles':'director'})).status_code == 200
    user = await session.scalar(select(User).where(User.username == 'dev-own'))
    user.status = 'inactive'
    await session.commit()
    assert (await api.get('/sales/clients', headers=headers)).status_code == 403
    assert (await api.get('/health', headers=headers)).status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("role,status", [("sales", "active"), ("onboarding", "onboarding")])
@pytest.mark.parametrize("event", ["identity.user.crm_access_requested", "identity.user.crm_role_change_requested"])
async def test_restoring_access_never_revives_pre_revocation_jwt(session, role, status, event):
    cutoff = datetime(2026, 9, 6, 12, 0, 0)
    issued = int(cutoff.replace(tzinfo=UTC).timestamp())
    session.add(User(username="restored", full_name="Synthetic restored", employee_id=77,
                    keycloak_user_id="kc-restored", role=role, status=status))
    session.add(AuditLog(actor="director", action=event, entity_ref="employee:77", ts=cutoff,
                        detail={"enabled": False}))
    await session.commit()
    for timestamp in [None, issued - 1, issued]:
        old = CurrentUser("restored", [role], "kc-restored", issued_at=timestamp)
        assert (await resolve_effective_oidc_user(old, session)).roles == [GUEST]
    fresh = CurrentUser("restored", [role], "kc-restored", issued_at=issued + 1)
    assert (await resolve_effective_oidc_user(fresh, session)).roles == [role]


@pytest.mark.asyncio
async def test_visibility_and_other_employee_events_do_not_require_fresh_login(session):
    session.add(User(username="current", full_name="Synthetic current", employee_id=77,
                    keycloak_user_id="kc-current", role="sales", status="active", deal_visibility="own"))
    session.add_all([
        AuditLog(actor="director", action="identity.user.crm_access_requested", entity_ref="employee:88", detail={}),
        AuditLog(actor="director", action="identity.user.crm_visibility_changed", entity_ref="employee:77", detail={}),
    ])
    await session.commit()
    effective = await resolve_effective_oidc_user(CurrentUser("current", ["sales"], "kc-current"), session)
    assert effective.roles == ["sales"] and effective.deal_visibility == "own"


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
async def test_managed_crm_identity_is_restricted_without_changing_legacy_role_matrix(session, monkeypatch):
    from config.access import ACCESS_MATRIX
    from core.domain.models import Counterparty

    buyer = Counterparty(name="Synthetic client", unp="123456789",
                         requisites={"legal_address": "Synthetic test address"})
    session.add(buyer)
    session.add(User(username="managed-crm", full_name="Synthetic CRM", keycloak_user_id="kc-managed-crm",
                     role="sales_head", status="active", expected_department="Продажи", expected_role="sales_head"))
    await session.commit()
    claimed = CurrentUser("managed-crm", ["sales_head", "director"], "kc-managed-crm")
    effective = await resolve_effective_oidc_user(claimed, session)
    assert effective.roles == ["sales_head"]
    assert effective.crm_restricted is True
    assert "marketing" in ACCESS_MATRIX["sales_head"]
    async with await _effective_access_client(session, monkeypatch, claimed) as api:
        access = await api.get("/system/access")
        assert access.status_code == 200
        assert access.json()["matrix"] == {"sales_head": ["home", "crm"]}
        deals = await api.get("/sales/deals")
        assert deals.status_code == 200, deals.text
        created = await api.post("/sales/deals", json={"number": "SYNTHETIC-CRM-ONLY-1", "title": "Synthetic deal", "counterparty": buyer.name, "counterparty_id": buyer.id})
        assert created.status_code == 201, created.text
        assert created.json()["counterparty_id"] == buyer.id
        assert created.json()["counterparty"] == buyer.name
        updated = await api.patch(f"/sales/deals/{created.json()['id']}", json={"title": "Updated synthetic deal"})
        assert updated.status_code == 200, updated.text
        for path in ["/hr/employees", "/finance", "/marketing", "/knowledge", "/system/users/crm-staff", "/system/reference/skus"]:
            assert (await api.get(path)).status_code == 403
        assert (await api.delete("/sales/deal-items/1")).status_code == 403
        assert (await api.post("/sales/stages", json={})).status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("role,restricted", [("sales", True), ("sales_manager", False), ("sales_cli", True), ("sales_head", True)])
async def test_own_crm_can_pick_real_sku_with_existing_role_boundaries(session, monkeypatch, role, restricted):
    from core.domain.models import Sku
    from modules.integrations.models import StockItem
    from modules.sales.models import Deal, DealItem

    user = User(username="synthetic-catalog-seller", full_name="Synthetic seller",
                keycloak_user_id="kc-synthetic-catalog", role=role, status="active",
                employee_id=401, deal_visibility="own",
                expected_department="Продажи", expected_role=role)
    sku = Sku(code="SYNTHETIC-CATALOG-SKU", title="Synthetic battery", unit="шт",
              attributes={"internal_fixture_note": "not part of the seller DTO"})
    own = Deal(number="SYNTHETIC-CATALOG-OWN", title="Synthetic own deal",
               counterparty="Synthetic buyer", owner_id=401)
    foreign = Deal(number="SYNTHETIC-CATALOG-FOREIGN", title="Synthetic foreign deal",
                   counterparty="Synthetic foreign buyer", owner_id=402)
    stocks = [
        StockItem(sku_code=sku.code, warehouse="SYNTHETIC-NORTH", qty_available=12,
                  qty_reserved=5, qty_forecast=2, price=150, cost=100),
        StockItem(sku_code=sku.code, warehouse="SYNTHETIC-SOUTH", qty_available=4,
                  qty_reserved=1, qty_forecast=0, price=165, cost=110),
    ]
    session.add_all([user, sku, own, foreign, *stocks])
    await session.commit()
    claimed = CurrentUser(user.username, [role, "director"], user.keycloak_user_id)
    effective = await resolve_effective_oidc_user(claimed, session)
    assert effective.roles == [role] and effective.crm_restricted is restricted
    async with await _effective_access_client(session, monkeypatch, claimed) as api:
        products = await api.get("/sales/skus?for_picker=1")
        assert products.status_code == 200, products.text
        assert products.json() == [{"id": sku.id, "code": sku.code, "title": sku.title, "unit": sku.unit}]
        stock = await api.get("/sales/picker-stock")
        assert stock.status_code == 200, stock.text
        rows = stock.json()
        assert len(rows) == 2
        assert {row["warehouse"]: row for row in rows} == {
            "SYNTHETIC-NORTH": {"sku_code": sku.code, "warehouse": "SYNTHETIC-NORTH",
                                "qty_available": 12, "qty_reserved": 5, "qty_forecast": 2,
                                "price": 150, "cost": None if restricted else 100},
            "SYNTHETIC-SOUTH": {"sku_code": sku.code, "warehouse": "SYNTHETIC-SOUTH",
                                "qty_available": 4, "qty_reserved": 1, "qty_forecast": 0,
                                "price": 165, "cost": None if restricted else 110},
        }
        if restricted:
            assert (await api.get("/integrations/1c/stock")).status_code == 403
        listing = await api.get("/sales/deals")
        assert listing.status_code == 200
        assert [row["id"] for row in listing.json()] == [own.id]
        if restricted:
            for path in ["/system/reference/skus", "/system/references/quality"]:
                assert (await api.get(path)).status_code == 403
        assert (await api.get("/system/mdm/counterparty/1")).status_code == 403
        for path in [f"/sales/deals/{foreign.id}", f"/sales/deals/{foreign.id}/items"]:
            assert (await api.get(path)).status_code == 404
        payload = {"sku_id": sku.id, "qty": 3, "unit_price": 25,
                   "request_key": "00000000-0000-4000-8000-000000000401"}
        rejected = await api.post(f"/sales/deals/{foreign.id}/items", json=payload)
        assert rejected.status_code == 404, rejected.text
        created = await api.post(f"/sales/deals/{own.id}/items", json=payload)
        assert created.status_code == 201, created.text
        rows = await api.get(f"/sales/deals/{own.id}/items")
        assert rows.status_code == 200 and len(rows.json()) == 1
        assert rows.json()[0]["sku_id"] == sku.id
        assert rows.json()[0]["qty"] == 3 and rows.json()[0]["unit_price"] == 25
        assert await session.scalar(select(DealItem.id).where(DealItem.deal_id == foreign.id)) is None


@pytest.mark.asyncio
async def test_legacy_linked_crm_without_invitation_metadata_keeps_existing_scope(session):
    session.add(User(username="legacy-crm", full_name="Legacy CRM", keycloak_user_id="kc-legacy-crm",
                     role="sales_head", status="active"))
    await session.commit()
    effective = await resolve_effective_oidc_user(CurrentUser("legacy-crm", ["sales_head"], "kc-legacy-crm"), session)
    assert effective.roles == ["sales_head"]
    assert effective.crm_restricted is False


@pytest.mark.asyncio
async def test_identity_lookup_failure_is_explicit_and_contains_no_database_details(session):
    await session.execute(text("DROP TABLE app_user"))

    with pytest.raises(EffectiveIdentityLookupError) as exc_info:
        await resolve_effective_oidc_user(CurrentUser("user", ["sales"], "kc-user"), session)

    assert str(exc_info.value) == "effective_identity_lookup_failed"


@pytest.mark.asyncio
@pytest.mark.parametrize("status,role", [(None, GUEST), ("suspended", "sales"), ("active", "hr")])
async def test_picker_stock_rejects_missing_suspended_and_non_sales_identity(session, monkeypatch, status, role):
    username, subject = "synthetic-stock-denied", "synthetic-stock-denied-subject"
    if status is not None:
        session.add(User(username=username, full_name="Synthetic denied user", keycloak_user_id=subject,
                         status=status, role=role))
        await session.commit()
    async with await _effective_access_client(session, monkeypatch, CurrentUser(username, [role], subject)) as api:
        response = await api.get("/sales/picker-stock")
        assert response.status_code == 403
        assert set(response.json()) == {"detail"}


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
    from modules.leads.models import Lead
    owned = Lead(name='Owned', owner_id=100)
    foreign = Lead(name='Foreign', owner_id=200)
    unassigned = Lead(name='Unassigned')
    session.add_all([owned, foreign, unassigned])
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
            ("GET", "/leads/plan"), ("GET", "/leads/managers"),
            ("GET", "/leads/stats/sources"),
            ("GET", "/service/requests"), ("PATCH", "/service/requests/1"),
            ("GET", "/system/mdm/counterparty/1"),
            ("GET", "/system/mdm/counterparty/1/"),
        ):
            result = await client.request(method, path)
            assert result.status_code == 403, (method, path, result.text)
        # Leads now resolve the same signed identity through their own numeric
        # scope; neighboring APIs keep their blanket denial.
        listing = await client.get('/leads')
        assert listing.status_code == 200
        assert [row['id'] for row in listing.json()] == [owned.id]
        assert listing.headers['X-CRM-Visibility'] == 'own'
        assert (await client.get(f'/leads/{owned.id}')).status_code == 200
        for hidden_id in [foreign.id, unassigned.id]:
            for method, suffix in [('GET', ''), ('GET', '/items'), ('POST', '/qualify'), ('POST', '/route'), ('POST', '/convert')]:
                result = await client.request(method, f'/leads/{hidden_id}{suffix}')
                expected = 403 if role == 'sales_cli' and suffix in {'/route', '/convert'} else 404
                assert result.status_code == expected, (method, hidden_id, result.text)
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


@pytest.mark.asyncio
async def test_alias_subjects_keep_separate_roles_scope_and_shared_revocation(session):
    accounts = [
        User(username="synthetic-alias-a", full_name="Synthetic employee", employee_id=9901,
             keycloak_user_id="synthetic-subject-a", role="director", status="active", deal_visibility="all"),
        User(username="synthetic-alias-b", full_name="Synthetic employee", employee_id=9901,
             keycloak_user_id="synthetic-subject-b", role="sales", status="active", deal_visibility="own"),
    ]
    session.add_all(accounts)
    await session.commit()
    cutoff = datetime(2026, 7, 1, 12)
    issued = int(cutoff.replace(tzinfo=UTC).timestamp())
    for account in accounts:
        principal = CurrentUser(account.username, [account.role], account.keycloak_user_id, issued_at=issued)
        resolved = await resolve_effective_oidc_user(principal, session)
        assert resolved.roles == [account.role]
        assert resolved.deal_visibility == account.deal_visibility
    session.add(AuditLog(actor="synthetic-director", action="identity.user.crm_access_requested",
                         entity_ref="employee:9901", ts=cutoff, detail={"enabled": False}))
    await session.commit()
    for account in accounts:
        stale = CurrentUser(account.username, [account.role], account.keycloak_user_id, issued_at=issued)
        assert (await resolve_effective_oidc_user(stale, session)).roles == [GUEST]
        fresh = CurrentUser(account.username, [account.role], account.keycloak_user_id, issued_at=issued + 1)
        assert (await resolve_effective_oidc_user(fresh, session)).roles == [account.role]
