from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from core.services.auth import CurrentUser, get_current_user
from modules.accounting import expenses
from modules.accounting.expense_models import ExpenseCommandReceipt
from modules.accounting.expense_routes import router
from modules.accounting.expense_schemas import CatalogCommand
from modules.accounting.models import AccessGrant, Account, Entry, Line, Organization, Policy


@pytest.fixture
def expense_client(client):
    client.test_app.include_router(router, prefix="/accounting")
    return client


def body(**changes):
    return {
        "request_key": str(uuid4()),
        "expected_revision": 0,
        "evidence": "Synthetic template choice",
        "action": "template",
        **changes,
    }


@pytest.mark.parametrize("method,path", [("GET", "/expense-catalog"), ("POST", "/expense-catalog/commands")])
async def test_identity_revoked_while_waiting_cannot_read_or_write(expense_client, db, book, monkeypatch, method, path):
    from modules.accounting import expense_routes
    calls = 0

    async def effective(user, session):
        nonlocal calls
        calls += 1
        return CurrentUser("tester", ["director"], local_status="active" if calls == 1 else "disabled")

    monkeypatch.setattr(expense_routes, "resolve_effective_oidc_user", effective)
    response = await expense_client.request(method, f"/accounting/organizations/{book[0]}" + path,
        **({"json": body(), "headers": {"X-Expected-Principal": "tester"}} if method == "POST" else {}))
    assert response.status_code == 403
    assert calls == 2
    assert (await db.scalars(select(ExpenseCommandReceipt))).all() == []


async def test_context_does_not_create_catalog_and_exposes_approval(expense_client, db, book):
    url = f"/accounting/organizations/{book[0]}"
    value = (await expense_client.get(url + "/expense-catalog")).json()
    assert value["principal"] == "tester" and value["organization_id"] == book[0]
    assert value["catalog"]["groups"] == [] and value["approval_enabled"] is True
    assert value["approval_blocker"] is None
    response = await expense_client.get(url + "/expense-budgets?year=2026&currency=BYN&basis=cash")
    assert response.status_code == 200
    assert response.json()["versions"] == [] and response.json()["approved_plan"] is None
    assert all(
        v["amount"] is None and v["coverage"] == "unknown"
        for v in response.json()["actuals"].values()
    )
    actuals = await expense_client.get(
        url + "/expense-actuals?year=2026&month=10&currency=BYN&basis=accrual"
    )
    assert actuals.status_code == 200
    assert actuals.json()["actuals"]["amount"] is None
    assert actuals.json()["actuals"]["coverage"] == "unknown"
    assert (await expense_client.post(url + "/expense-budgets/approve", json={})).status_code == 422
    assert (await db.scalars(select(ExpenseCommandReceipt))).all() == []


async def test_unmatched_actuals_mirrors_actuals_scope_and_never_guesses_article(db, book):
    catalog = await expenses.execute(db, book[0], "tester", "catalog", CatalogCommand(**body()))
    await db.commit()
    article_id = catalog["result"]["articles"][0]["id"]
    policy = await db.get(Policy, book[1])
    account = await db.scalar(select(Account).where(Account.organization_id == book[0], Account.code == "90.4"))
    other = Organization(name="Other expense company", unp="888888888")
    db.add(other)
    await db.flush()

    def entry(key, *, org_id=book[0], month=10):
        posting_date = date(2026, month, 5)
        return Entry(
            organization_id=org_id, source=f"expense-register-{key}", source_version=1,
            operation=f"manual-{key}", document_date=posting_date, operation_date=posting_date,
            posting_date=posting_date, policy_id=policy.id, rule_version="test",
            explanation="Synthetic unmatched register row", opening=False, correction_of=None,
            digest=(key + "0" * 64)[:64], actor="tester",
        )

    entries = {
        "missing": entry("missing"),
        "missing_catalog": entry("missing-catalog"),
        "counterparty": entry("counterparty"),
        "matched": entry("matched"),
        "cash_missing": entry("cash-missing"),
        "cash_matched": entry("cash-matched"),
        "wrong_month": entry("wrong-month", month=11),
        "other_org": entry("other-org", org_id=other.id),
        "wrong_category": entry("wrong-category"),
        "wrong_currency": entry("wrong-currency"),
    }
    db.add_all(entries.values())
    await db.flush()

    def line(key, *, dimensions=None, cash=False, category="expense", currency="BYN"):
        row = entries[key]
        return Line(
            entry_id=row.id, account_id=account.id, account_code=account.code, account_title=account.title,
            category=category, cash=cash, side="debit", amount=Decimal("1.00"),
            dimensions=dimensions or {}, currency=currency,
        )

    lines = {
        "missing": line("missing"),
        "missing_catalog": line("missing_catalog", dimensions={"expense_article_id": "999999"}),
        "counterparty": line("counterparty", dimensions={"counterparty": "supplier-7"}),
        "matched": line("matched", dimensions={"expense_article_id": str(article_id)}),
        "cash_missing": line("cash_missing", cash=True),
        "cash_matched": line("cash_matched", cash=True, dimensions={"expense_article_id": str(article_id)}),
        "wrong_month": line("wrong_month"),
        "other_org": line("other_org"),
        "wrong_category": line("wrong_category", category="income"),
        "wrong_currency": line("wrong_currency", currency="USD"),
    }
    db.add_all(lines.values())
    await db.flush()

    accrual = await expenses.actuals(db, book[0], 2026, 10, "accrual")
    register = await expenses.unmatched_actuals(db, book[0], 2026, 10, "accrual", limit=100)
    assert accrual["matched_lines"] == 2
    assert accrual["unmatched_lines"] == 4
    assert {row["line_id"] for row in register["items"]} == {
        lines[key].id for key in ("missing", "missing_catalog", "counterparty", "cash_missing")
    }
    by_line = {row["line_id"]: row for row in register["items"]}
    assert by_line[lines["missing"].id]["reason"] == "нет статьи"
    assert by_line[lines["missing_catalog"].id]["reason"] == "статья отсутствует в текущем справочнике"
    assert by_line[lines["counterparty"].id]["dimensions"] == {"counterparty": "supplier-7"}
    assert register["next_after_line_id"] is None

    cash = await expenses.actuals(db, book[0], 2026, 10, "cash")
    cash_register = await expenses.unmatched_actuals(db, book[0], 2026, 10, "cash", limit=100)
    assert cash["matched_lines"] == 1 and cash["unmatched_lines"] == 1
    assert [row["line_id"] for row in cash_register["items"]] == [lines["cash_missing"].id]


async def test_unmatched_actuals_pages_by_line_id_without_skipping_between_matched_rows(db, book):
    catalog = await expenses.execute(db, book[0], "tester", "catalog", CatalogCommand(**body()))
    await db.commit()
    article_id = catalog["result"]["articles"][0]["id"]
    policy = await db.get(Policy, book[1])
    account = await db.scalar(select(Account).where(Account.organization_id == book[0], Account.code == "90.4"))

    def entry(key):
        posting_date = date(2026, 10, 5)
        return Entry(
            organization_id=book[0], source=f"expense-page-{key}", source_version=1,
            operation=f"manual-{key}", document_date=posting_date, operation_date=posting_date,
            posting_date=posting_date, policy_id=policy.id, rule_version="test",
            explanation="Synthetic paging row", opening=False, correction_of=None,
            digest=(key + "0" * 64)[:64], actor="tester",
        )

    entries = {key: entry(key) for key in ("u1", "m1", "u2", "m2", "u3")}
    db.add_all(entries.values())
    await db.flush()

    def line(key, dimensions):
        return Line(
            entry_id=entries[key].id, account_id=account.id, account_code=account.code,
            account_title=account.title, category="expense", cash=False, side="debit",
            amount=Decimal("1.00"), dimensions=dimensions, currency="BYN",
        )

    lines = {
        key: line(key, {} if key.startswith("u") else {"expense_article_id": str(article_id)})
        for key in ("u1", "u2", "u3", "m1", "m2")
    }
    # Entry order and Line.id order intentionally differ. The cursor must follow
    # Line.id even when matching rows sit between unmatched rows in the register.
    db.add_all([lines[key] for key in ("u1", "u2", "u3", "m1", "m2")])
    await db.flush()

    first = await expenses.unmatched_actuals(db, book[0], 2026, 10, "accrual", limit=1)
    second = await expenses.unmatched_actuals(
        db, book[0], 2026, 10, "accrual", after_line_id=first["next_after_line_id"], limit=1
    )
    third = await expenses.unmatched_actuals(
        db, book[0], 2026, 10, "accrual", after_line_id=second["next_after_line_id"], limit=1
    )
    assert [row["line_id"] for row in first["items"]] == [lines["u1"].id]
    assert [row["line_id"] for row in second["items"]] == [lines["u2"].id]
    assert [row["line_id"] for row in third["items"]] == [lines["u3"].id]
    assert first["next_after_line_id"] == lines["u1"].id
    assert second["next_after_line_id"] == lines["u2"].id
    assert third["next_after_line_id"] is None


async def test_unmatched_endpoint_is_organization_principal_scoped_and_signed(expense_client, db, book):
    policy = await db.get(Policy, book[1])
    account = await db.scalar(select(Account).where(Account.organization_id == book[0], Account.code == "90.4"))
    posting_date = date(2026, 10, 5)
    entry = Entry(
        organization_id=book[0], source="expense-api-unmatched", source_version=1, operation="manual",
        document_date=posting_date, operation_date=posting_date, posting_date=posting_date,
        policy_id=policy.id, rule_version="test", explanation="Synthetic API row", opening=False,
        correction_of=None, digest="a" * 64, actor="tester",
    )
    db.add(entry)
    await db.flush()
    line = Line(
        entry_id=entry.id, account_id=account.id, account_code=account.code, account_title=account.title,
        category="expense", cash=False, side="debit", amount=Decimal("2.00"), dimensions={}, currency="BYN",
    )
    db.add(line)
    await db.flush()

    url = f"/accounting/organizations/{book[0]}/expense-actuals/unmatched?year=2026&month=10&currency=BYN&basis=accrual"
    response = await expense_client.get(url)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["organization_id"] == book[0] and payload["principal"] == "tester"
    assert payload["items"][0]["line_id"] == line.id
    unsigned = {key: value for key, value in payload.items() if key != "digest"}
    assert payload["digest"] == expenses.digest(unsigned)
    assert (await expense_client.get(url.replace(f"organizations/{book[0]}", "organizations/999"))).status_code == 403
    expense_client.test_app.dependency_overrides[get_current_user] = lambda: CurrentUser("anonymous", [])
    assert (await expense_client.get(url)).status_code == 403


async def test_header_scope_replay_and_missing_configuration(expense_client, book):
    url = f"/accounting/organizations/{book[0]}"
    command = body()
    assert (
        await expense_client.post(url + "/expense-catalog/commands", json=command)
    ).status_code == 422
    assert (
        await expense_client.post(
            url + "/expense-catalog/commands", json=command, headers={"X-Expected-Principal": "old"}
        )
    ).status_code == 409
    first = await expense_client.post(
        url + "/expense-catalog/commands", json=command, headers={"X-Expected-Principal": "tester"}
    )
    assert first.status_code == 200, first.text
    repeat = await expense_client.post(
        url + "/expense-catalog/commands", json=command, headers={"X-Expected-Principal": "tester"}
    )
    assert repeat.json() == first.json()
    recovered = await expense_client.get(url + "/expense-commands/" + command["request_key"])
    assert recovered.json() == first.json()
    assert (await expense_client.get(url + "/expense-budgets?year=2026")).status_code == 422
    assert (
        await expense_client.get("/accounting/organizations/999/expense-catalog")
    ).status_code == 403


async def test_reader_no_write_and_revocation_blocks_old_receipt(expense_client, db, book):
    url = f"/accounting/organizations/{book[0]}"
    command = body()
    first = await expense_client.post(
        url + "/expense-catalog/commands", json=command, headers={"X-Expected-Principal": "tester"}
    )
    assert first.status_code == 200
    grant = await db.scalar(select(AccessGrant).where(AccessGrant.organization_id == book[0]))
    grant.role = "reader"
    await db.commit()
    assert (await expense_client.get(url + "/expense-catalog")).status_code == 200
    assert (
        await expense_client.post(
            url + "/expense-catalog/commands",
            json=command,
            headers={"X-Expected-Principal": "tester"},
        )
    ).status_code == 403
    await db.delete(grant)
    await db.commit()
    assert (
        await expense_client.get(url + "/expense-commands/" + command["request_key"])
    ).status_code == 403
    expense_client.test_app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        "anonymous", []
    )
    assert (await expense_client.get(url + "/expense-catalog")).status_code == 403


async def test_accountant_can_save_drafts_but_cannot_mutate_catalog(expense_client, db, book):
    url = f"/accounting/organizations/{book[0]}"
    headers = {"X-Expected-Principal": "tester"}
    created = await expense_client.post(
        url + "/expense-catalog/commands", json=body(), headers=headers
    )
    article_id = created.json()["result"]["articles"][0]["id"]
    grant = await db.scalar(select(AccessGrant).where(AccessGrant.organization_id == book[0]))
    grant.role = "accountant"
    await db.commit()
    assert (
        await expense_client.post(url + "/expense-catalog/commands", json=body(), headers=headers)
    ).status_code == 403
    draft = {
        "request_key": str(uuid4()),
        "expected_revision": 0,
        "expected_catalog_revision": 1,
        "year": 2026,
        "currency": "BYN",
        "basis": "accrual",
        "evidence": "Explicit accountant draft",
        "lines": [{"article_id": article_id, "months": ["0.00"] + [None] * 11}],
    }
    result = await expense_client.post(url + "/expense-budgets/drafts", json=draft, headers=headers)
    assert result.status_code == 200, result.text
    assert result.json()["result"]["lines"][0]["months"] == ["0.00"] + [None] * 11
    assert (
        await expense_client.post(url + "/expense-budgets/drafts", json=draft, headers=headers)
    ).json() == result.json()
    historical = await expense_client.get(
        url + "/expense-budgets?year=2026&currency=BYN&basis=accrual"
    )
    assert len(historical.json()["versions"]) == 1
    approval = {
        "request_key": str(uuid4()), "budget_id": result.json()["result"]["id"],
        "expected_revision": result.json()["result"]["revision"], "evidence": "Accountant cannot approve",
    }
    assert (
        await expense_client.post(url + "/expense-budgets/approve", json=approval, headers=headers)
    ).status_code == 403
    assert (
        await expense_client.post(
            url + "/expense-budgets/drafts", json={**draft, "organization_id": 999}, headers=headers
        )
    ).status_code == 422


async def test_chief_approves_latest_budget_and_readback_is_scoped(expense_client, db, book):
    url = f"/accounting/organizations/{book[0]}"
    headers = {"X-Expected-Principal": "tester"}
    created = await expense_client.post(url + "/expense-catalog/commands", json=body(), headers=headers)
    article_id = created.json()["result"]["articles"][0]["id"]
    draft = {
        "request_key": str(uuid4()),
        "expected_revision": 0,
        "expected_catalog_revision": 1,
        "year": 2026,
        "currency": "BYN",
        "basis": "accrual",
        "evidence": "Подготовлена версия для утверждения",
        "lines": [{"article_id": article_id, "months": ["10.00"] + [None] * 11}],
    }
    saved = await expense_client.post(url + "/expense-budgets/drafts", json=draft, headers=headers)
    assert saved.status_code == 200, saved.text
    approval = {
        "request_key": str(uuid4()),
        "budget_id": saved.json()["result"]["id"],
        "expected_revision": saved.json()["result"]["revision"],
        "evidence": "Главный бухгалтер проверил версию",
    }
    first = await expense_client.post(url + "/expense-budgets/approve", json=approval, headers=headers)
    assert first.status_code == 200, first.text
    assert first.json()["kind"] == "budget_approval"
    repeat = await expense_client.post(url + "/expense-budgets/approve", json=approval, headers=headers)
    assert repeat.json() == first.json()
    view = await expense_client.get(url + "/expense-budgets?year=2026&currency=BYN&basis=accrual")
    assert view.status_code == 200
    assert view.json()["approved_plan"]["budget_id"] == approval["budget_id"]
    assert view.json()["approved_plan"]["budget"]["lines"][0]["months"][0] == "10.00"
