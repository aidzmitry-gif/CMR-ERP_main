from uuid import uuid4

import pytest
from sqlalchemy import select

from core.services.auth import CurrentUser, get_current_user
from modules.accounting.expense_models import ExpenseCommandReceipt
from modules.accounting.expense_routes import router
from modules.accounting.models import AccessGrant


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
