from datetime import date

import pytest
from sqlalchemy import select

from core.domain.reference import Currency
from core.services.auth import CurrentUser, get_current_user
from modules.accounting.gateway import AccountingService
from modules.accounting.models import AccessGrant, Organization, SellerProfile


def payload(**changes):
    value = dict(source_key="seller-1", expected_revision=0, effective_from="2026-01-01",
                 currency="BYN", address="Synthetic address", account="TEST ACCOUNT",
                 bank="Synthetic bank", bik="TEST BANK", director="Synthetic director",
                 evidence="Synthetic approved document requisites", confirmed=True)
    return {**value, **changes}


async def test_seller_history_exact_currency_and_idempotency(client, db, book):
    prefix = f"/accounting/organizations/{book[0]}"
    assert (await client.get(prefix + "/seller-profile?on=2026-09-01&currency=BYN")).status_code == 409
    first = await client.post(prefix + "/seller-profiles", json=payload())
    assert first.status_code == 201, first.text
    first = first.json()
    assert first["seller"]["unp"] == "999999999"
    assert first["seller"]["stamp_data_url"] is None
    assert first["seller"]["account"] == "TEST ACCOUNT"
    assert (await client.post(prefix + "/seller-profiles", json=payload())).json() == first
    assert (await client.post(prefix + "/seller-profiles", json=payload(bank="Changed"))).status_code == 409
    assert (await client.post(prefix + "/seller-profiles", json=payload(
        source_key="stale", expected_revision=0))).status_code == 409
    second = await client.post(prefix + "/seller-profiles", json=payload(
        source_key="seller-2", expected_revision=1, effective_from="2026-10-01", account="NEW ACCOUNT"))
    assert second.status_code == 201, second.text
    before = await client.get(prefix + "/seller-profile?on=2026-09-01&currency=BYN")
    after = await client.get(prefix + "/seller-profile?on=2026-10-01&currency=BYN")
    assert before.json() == first
    assert after.json()["seller"]["account"] == "NEW ACCOUNT"
    assert (await client.get(prefix + "/seller-profile?on=2026-10-01&currency=USD")).status_code == 409
    assert (await client.get(prefix + "/seller-profile?on=2025-12-31&currency=BYN")).status_code == 409
    versions = (await client.get(prefix + "/seller-profiles")).json()
    assert [row["revision"] for row in versions] == [2, 1]
    gateway = await AccountingService().invoice_seller(
        db, book[0], CurrentUser("tester", ["director"]), date(2026, 9, 1), "BYN")
    assert gateway == first
    await db.rollback()


@pytest.mark.parametrize("changes", [
    {"confirmed": False}, {"confirmed": "true"}, {"account": " "},
    {"address": ""}, {"currency": "byn"}, {"expected_revision": True},
    {"name": "Other company"}, {"unp": "123456789"},
])
async def test_profile_requires_explicit_requisites(client, db, book, changes):
    response = await client.post(f"/accounting/organizations/{book[0]}/seller-profiles",
                                 json=payload(**changes))
    assert response.status_code == 422, response.text
    assert await db.scalar(select(SellerProfile.id)) is None


async def test_seller_profile_scope_and_chief_authority(client, db, book):
    db.add(AccessGrant(organization_id=book[0], subject="reader", role="reader"))
    db.add(AccessGrant(organization_id=book[0], subject="accountant", role="accountant"))
    await db.commit()
    endpoint = f"/accounting/organizations/{book[0]}/seller-profiles"
    assert (await client.post(endpoint, json=payload())).status_code == 201
    for name in ("reader", "accountant", "foreign"):
        client.test_app.dependency_overrides[get_current_user] = lambda name=name: CurrentUser(name, ["director"])
        assert (await client.post(endpoint, json=payload(source_key=name, expected_revision=1))).status_code == 403
        response = await client.get(endpoint)
        assert response.status_code == (403 if name == "foreign" else 200)


async def test_profile_snapshot_survives_org_rename_and_rejects_edit(client, db, book):
    endpoint = f"/accounting/organizations/{book[0]}/seller-profiles"
    original = (await client.post(endpoint, json=payload())).json()
    org = await db.get(Organization, book[0])
    org.name = "Renamed synthetic organization"
    await db.commit()
    assert (await client.get(endpoint)).json()[0] == original
    profile = await db.get(SellerProfile, original["profile_id"])
    profile.evidence = "Changed"
    with pytest.raises(ValueError, match="immutable"):
        await db.commit()
    await db.rollback()


async def test_seller_currency_validation_preserves_history_and_replay(client, db, book):
    endpoint = f"/accounting/organizations/{book[0]}/seller-profiles"
    usd = await db.scalar(select(Currency).where(Currency.code == "USD"))
    usd.is_active = False
    await db.commit()
    for currency in ("ZZZ", "USD"):
        response = await client.post(endpoint, json=payload(currency=currency))
        assert response.status_code == 409, response.text
    usd.is_active = True
    await db.commit()
    request = payload(currency="USD")
    original = await client.post(endpoint, json=request)
    assert original.status_code == 201, original.text
    assert (await AccountingService().invoice_seller(
        db, book[0], CurrentUser("tester", ["director"]), date(2026, 9, 1), "USD"))["seller"]["currency"] == "USD"
    await db.rollback()
    # Reload after rollback expiration; current source must observe deactivation.
    usd = await db.scalar(select(Currency).where(Currency.code == "USD"))
    usd.is_active = False
    await db.commit()
    assert (await client.get(endpoint)).json() == [original.json()]
    assert (await client.post(endpoint, json=request)).json() == original.json()
    response = await client.get(f"/accounting/organizations/{book[0]}/seller-profile?on=2026-09-01&currency=USD")
    assert response.status_code == 409, response.text
