"""Current company catalog and identified source envelope for the cost viewer."""
from uuid import uuid4

from sqlalchemy import delete, select

from core.domain.models import User
from core.services.auth import CurrentUser, get_current_user
from modules.accounting.models import AccessGrant
from tests import test_logistics_owned_costs as costs

cost_book = costs.cost_book


async def test_catalog_contains_only_current_memberships(api, session, cost_book):
    response = await api.post("/accounting/organizations", json={"name": "Foreign hidden cost company", "unp": "999999965"})
    assert response.status_code == 201
    foreign = response.json()["id"]
    await session.execute(delete(AccessGrant).where(AccessGrant.organization_id == foreign))
    await session.commit()
    response = await api.get("/logistics/cost-organizations")
    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == "private, no-store"
    body = response.json()
    assert body["version"] == 1 and body["principal"] == "logistics-cost-owner"
    assert [item["id"] for item in body["items"]] == [cost_book]
    assert "Foreign hidden" not in response.text


async def test_review_envelope_returns_authoritative_principal_and_no_store(api, session, cost_book):
    await costs.add_import(api, session, cost_book, "17000.00")
    response = await api.get(f"/logistics/organizations/{cost_book}/cost-insights")
    assert response.status_code == 200, response.text
    assert response.json()["principal"] == "logistics-cost-owner"
    assert response.json()["import_freight"]["total"] == "17000.00"
    assert response.headers["Cache-Control"] == "private, no-store"


async def test_catalog_refuses_missing_access_facade(api, cost_book, monkeypatch):
    monkeypatch.setattr(api._transport.app.state.core.services, "accounting", None)
    response = await api.get("/logistics/cost-organizations")
    assert response.status_code == 503
    assert response.json()["detail"] == "accounting_source_access_unavailable"


async def test_catalog_refuses_inactive_identity(api, session, cost_book):
    user = await session.scalar(select(User).where(User.username == "logistics-cost-owner"))
    user.status = "inactive"
    await session.commit()
    assert (await api.get("/logistics/cost-organizations")).status_code == 403


async def test_stable_subject_is_distinct_from_renamed_username(api, session, cost_book):
    stable = str(uuid4())
    user = await session.scalar(select(User).where(User.username == "logistics-cost-owner"))
    user.keycloak_user_id = stable
    session.add(AccessGrant(organization_id=cost_book, subject=stable, role="reader"))
    await session.commit()

    async def identity():
        return CurrentUser("renamed-display", ["director"], keycloak_user_id=stable)

    app = api._transport.app
    old = app.dependency_overrides.get(get_current_user)
    app.dependency_overrides[get_current_user] = identity
    try:
        catalog = await api.get("/logistics/cost-organizations")
        assert catalog.status_code == 200, catalog.text
        assert catalog.json()["principal"] == stable
        assert [row["id"] for row in catalog.json()["items"]] == [cost_book]
        review = await api.get(f"/logistics/organizations/{cost_book}/cost-insights")
        assert review.status_code == 200, review.text
        assert review.json()["principal"] == stable
    finally:
        if old is None:
            app.dependency_overrides.pop(get_current_user, None)
        else:
            app.dependency_overrides[get_current_user] = old
