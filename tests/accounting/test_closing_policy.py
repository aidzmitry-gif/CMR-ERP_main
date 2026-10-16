from copy import deepcopy
from datetime import date

import pytest
from sqlalchemy import select

from modules.accounting.models import Account, Policy


def policy_body():
    return dict(effective_from="2026-10-01", reference="Synthetic policy", inventory_method="specific",
                allocation_basis="direct_cost", depreciation_method="straight_line",
                normative_reference="Synthetic only", normative_verified=False,
                financial_closing=dict(monthly_accounts=["90.1", "90.4"], result_account="99",
                    retained_earnings_account="84", year_end_month=12,
                    result_dimensions={"department": "test"}, retained_dimensions={},
                    opening_balance_treatment="include", reference="Synthetic closing instruction"))


async def seed_accounts(db, org):
    for code, category, dimensions in [("99", "income", ["department"]), ("84", "equity", [])]:
        db.add(Account(organization_id=org, code=code, title="Synthetic " + code, category=category,
                       valid_from=date(2026, 1, 1), required_dimensions=dimensions,
                       currency_tracking=False, quantity_tracking=False, cash=False, normative_ref="Synthetic"))
    await db.commit()


async def test_closing_settings_are_explicit_versioned_and_not_certified(client, db, book):
    await seed_accounts(db, book[0])
    prefix = f"/accounting/organizations/{book[0]}/policies"
    body = policy_body()
    response = await client.post(prefix, json=body)
    assert response.status_code == 201, response.text
    assert response.json()["financial_closing"] == body["financial_closing"]
    assert response.json()["normative_verified"] is False
    versions = (await client.get(prefix)).json()
    assert next(p for p in versions if p["id"] == book[1])["financial_closing"] is None
    row = await db.get(Policy, response.json()["id"])
    row.financial_closing = {**row.financial_closing, "year_end_month": 6}
    with pytest.raises(ValueError, match="immutable"):
        await db.flush()
    await db.rollback()


@pytest.mark.parametrize("field,value", [
    ("monthly_accounts", ["90.1", "90.1"]), ("monthly_accounts", []),
    ("monthly_accounts", ["99"]), ("monthly_accounts", ["51"]),
    ("result_account", "41"), ("result_account", "98"),
    ("retained_earnings_account", "60"), ("year_end_month", True),
    ("year_end_month", 13), ("result_dimensions", {}),
    ("result_dimensions", {"department": " "}),
    ("retained_dimensions", {"department": "unexpected"}),
    ("opening_balance_treatment", "guess"),
])
async def test_invalid_closing_configuration_does_not_create_policy(client, db, book, field, value):
    await seed_accounts(db, book[0])
    body = deepcopy(policy_body())
    body["financial_closing"][field] = value
    response = await client.post(f"/accounting/organizations/{book[0]}/policies", json=body)
    assert response.status_code == 422, response.text
    versions = (await db.scalars(select(Policy).where(Policy.organization_id == book[0]))).all()
    assert len(versions) == 1


async def test_closing_does_not_resolve_other_organization_accounts(client, db, book):
    other = await client.post("/accounting/organizations", json={"name": "Other synthetic", "unp": "888888888"})
    await seed_accounts(db, other.json()["id"])
    response = await client.post(f"/accounting/organizations/{book[0]}/policies", json=policy_body())
    assert response.status_code == 422 and "must exist in this organization" in response.text
