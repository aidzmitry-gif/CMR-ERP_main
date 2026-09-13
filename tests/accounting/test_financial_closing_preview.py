import pytest
from sqlalchemy import func, select, update

from modules.accounting.models import Entry, Period
from tests.accounting.test_closing_policy import policy_body


async def setup_policy(client, book, year_end=12, opening="include", normative_verified=False):
    prefix = f"/accounting/organizations/{book[0]}"
    for code, category, dimensions in [("701", "income", ["department"]), ("702", "expense", []),
                                       ("703", "income", ["department"]), ("704", "equity", [])]:
        response = await client.post(prefix + "/accounts", json=dict(code=code, title="Synthetic " + code,
            category=category, required_dimensions=dimensions, valid_from="2026-01-01",
            currency_tracking=False, quantity_tracking=False, cash=False, normative_ref="Synthetic only"))
        assert response.status_code == 201, response.text
    body = policy_body()
    body["normative_verified"] = normative_verified
    body["financial_closing"].update(monthly_accounts=["701", "702"], result_account="703",
        retained_earnings_account="704", year_end_month=year_end, opening_balance_treatment=opening)
    response = await client.post(prefix + "/policies", json=body)
    assert response.status_code == 201, response.text
    return prefix, response.json()["id"]


async def post(client, prefix, posting, policy, source, debit, credit, amount, department="source", **changes):
    data = posting(source, debit, credit, amount, policy_id=policy,
        document_date="2026-10-01", operation_date="2026-10-01", posting_date="2026-10-01",
        **changes).model_dump(mode="json")
    for line in data["lines"]:
        if line["account"] in {"701", "703"}:
            line["dimensions"] = {"department": department}
    response = await client.post(prefix + "/entries", json=data)
    assert response.status_code == 201, response.text


@pytest.mark.parametrize("income,expense,year_end,annual_side,annual_amount", [
    ("180.00", "100.00", 12, None, None),
    ("180.00", "100.00", 10, "credit", "80.00"),
    ("80.00", "180.00", 10, "debit", "100.00"),
    ("100.00", "100.00", 10, None, None),
])
async def test_monthly_and_annual_exact_preview_without_posting(client, db, book, posting, income, expense, year_end, annual_side, annual_amount):
    prefix, policy = await setup_policy(client, book, year_end)
    await post(client, prefix, posting, policy, "income", "62", "701", income)
    await post(client, prefix, posting, policy, "expense", "702", "60", expense)
    before = await db.scalar(select(func.count()).select_from(Entry))
    response = await client.get(prefix + "/periods/2026-10/financial-closing-preview")
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["confirmation_available"] is False and result["status"] == "preview_only"
    assert result["normative_verified"] is False
    assert len(result["monthly_lines"]) == 4  # Equal income/expense is not an empty close.
    assert result["monthly_lines"][0]["dimensions"] == {"department": "source"}
    assert result["monthly_lines"][1]["dimensions"] == {"department": "test"}
    if annual_side:
        assert result["annual_lines"][-1] == {"account": "704", "dimensions": {}, "side": annual_side, "amount": annual_amount}
    else:
        assert result["annual_lines"] == []
    assert (await client.get(prefix + "/periods/2026-10/financial-closing-preview")).json() == result
    assert await db.scalar(select(func.count()).select_from(Entry)) == before
    await post(client, prefix, posting, policy, "more-income", "62", "701", "1.00")
    changed = (await client.get(prefix + "/periods/2026-10/financial-closing-preview")).json()
    assert changed["basis_digest"] != result["basis_digest"]


@pytest.mark.parametrize("treatment,expected", [("include", 2), ("exclude", 0)])
async def test_opening_treatment_is_applied(client, db, book, posting, treatment, expected):
    prefix, policy = await setup_policy(client, book, opening=treatment)
    await post(client, prefix, posting, policy, "opening", "62", "701", "20.00", opening=True)
    response = await client.get(prefix + "/periods/2026-10/financial-closing-preview")
    assert response.status_code == 200, response.text
    assert len(response.json()["monthly_lines"]) == expected


async def test_missing_settings_block_and_empty_preview_creates_no_period(client, db, book):
    prefix = f"/accounting/organizations/{book[0]}"
    response = await client.get(prefix + "/periods/2026-09/financial-closing-preview")
    assert response.status_code == 422
    await setup_policy(client, book)
    response = await client.get(prefix + "/periods/2026-10/financial-closing-preview")
    assert response.status_code == 200, response.text
    assert response.json()["monthly_lines"] == []
    assert await db.scalar(select(func.count()).select_from(Period)) == 0


async def test_annual_closes_offsetting_result_analytics_individually(client, db, book, posting):
    prefix, policy = await setup_policy(client, book, year_end=10)
    await post(client, prefix, posting, policy, "result-A", "62", "703", "100.00", department="A")
    await post(client, prefix, posting, policy, "result-B", "703", "60", "100.00", department="B")
    response = await client.get(prefix + "/periods/2026-10/financial-closing-preview")
    assert response.status_code == 200, response.text
    assert response.json()["monthly_lines"] == []
    lines = response.json()["annual_lines"]
    assert len(lines) == 4
    assert lines[0] == {"account": "703", "dimensions": {"department": "A"}, "side": "debit", "amount": "100.00"}
    assert lines[2] == {"account": "703", "dimensions": {"department": "B"}, "side": "credit", "amount": "100.00"}


async def test_midmonth_policy_change_blocks_ambiguous_calculation(client, db, book):
    prefix, _ = await setup_policy(client, book)
    policy = (await client.get(prefix + "/policies")).json()[-1]
    body = policy_body()
    body["financial_closing"] = {**policy["financial_closing"], "opening_balance_treatment": "exclude"}
    body["effective_from"] = "2026-10-15"
    created = await client.post(prefix + "/policies", json=body)
    assert created.status_code == 201, created.text
    response = await client.get(prefix + "/periods/2026-10/financial-closing-preview")
    assert response.status_code == 422 and "changed within" in response.text


@pytest.mark.parametrize("closed", [False, True])
async def test_preview_refreshes_retained_period_after_lock(client, db, book, monkeypatch, closed):
    from modules.accounting import financial_closing

    prefix, _ = await setup_policy(client, book)
    retained = Period(organization_id=book[0], month="2026-10", generation=1, closed=False)
    db.add(retained)
    await db.commit()
    original = financial_closing.lock_organization

    async def changed_at_lock(session, org):
        await session.execute(update(Period).where(Period.id == retained.id)
            .values(generation=7, closed=closed).execution_options(synchronize_session=False))
        assert retained.generation == 1 and retained.closed is False
        return await original(session, org)

    monkeypatch.setattr(financial_closing, "lock_organization", changed_at_lock)
    response = await client.get(prefix + "/periods/2026-10/financial-closing-preview")
    if closed:
        assert response.status_code == 422 and "Reopen" in response.text
    else:
        assert response.status_code == 200, response.text
        assert response.json()["period_generation"] == 7
