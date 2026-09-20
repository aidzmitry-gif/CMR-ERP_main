"""HTTP boundary for immutable expense-article attribution."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from modules.accounting.expense_routes import router
from modules.accounting.models import AccessGrant, Account, Entry, Line, Policy


@pytest.fixture
def attribution_client(client):
    client.test_app.include_router(router, prefix="/accounting")
    return client


async def api_source(db, book):
    policy = await db.get(Policy, book[1])
    account = await db.scalar(
        select(Account).where(Account.organization_id == book[0], Account.code == "90.4")
    )
    entry = Entry(
        organization_id=book[0], source="expense-attribution-api", source_version=1,
        operation="manual", document_date=date(2026, 10, 5), operation_date=date(2026, 10, 5),
        posting_date=date(2026, 10, 5), policy_id=policy.id, rule_version="test",
        explanation="Synthetic API attribution source", opening=False, correction_of=None,
        digest="b" * 64, actor="tester",
    )
    db.add(entry)
    await db.flush()
    line = Line(
        entry_id=entry.id, account_id=account.id, account_code=account.code,
        account_title=account.title, category="expense", cash=False, side="debit",
        amount=Decimal("7.00"), dimensions={}, currency="BYN",
    )
    db.add(line)
    await db.flush()
    return line


async def test_accountant_can_preview_confirm_replay_and_read_own_attribution(attribution_client, db, book):
    prefix = f"/accounting/organizations/{book[0]}"
    headers = {"X-Expected-Principal": "tester"}
    catalog = await attribution_client.post(
        prefix + "/expense-catalog/commands",
        headers=headers,
        json={
            "request_key": str(uuid4()), "expected_revision": 0,
            "evidence": "Synthetic catalog", "action": "template",
        },
    )
    assert catalog.status_code == 200, catalog.text
    article_id = catalog.json()["result"]["articles"][0]["id"]
    line = await api_source(db, book)
    grant = await db.scalar(select(AccessGrant).where(AccessGrant.organization_id == book[0]))
    grant.role = "accountant"
    await db.commit()
    preview_body = {"source_line_id": line.id, "article_id": article_id, "effective_date": "2026-10-05"}
    preview = await attribution_client.post(
        prefix + "/expense-attributions/preview", json=preview_body, headers=headers
    )
    assert preview.status_code == 200, preview.text
    view = preview.json()
    assert view["organization_id"] == book[0] and view["principal"] == "tester"
    command = {
        **preview_body,
        "request_key": str(uuid4()),
        "expected_basis_digest": view["preview"]["basis_digest"],
        "evidence": "Проверен первичный документ",
        "explanation": "Ручное разнесение строки в открытом периоде",
    }
    first = await attribution_client.post(prefix + "/expense-attributions", json=command, headers=headers)
    assert first.status_code == 200, first.text
    assert first.json()["result"]["source_line_id"] == line.id
    repeat = await attribution_client.post(prefix + "/expense-attributions", json=command, headers=headers)
    assert repeat.json() == first.json()
    recovered = await attribution_client.get(prefix + "/expense-attributions/" + command["request_key"])
    assert recovered.json() == first.json()
    assert (
        await attribution_client.post(
            prefix + "/expense-attributions", json=command, headers={"X-Expected-Principal": "old"}
        )
    ).status_code == 409
    grant.role = "reader"
    await db.commit()
    assert (
        await attribution_client.post(prefix + "/expense-attributions", json=command, headers=headers)
    ).status_code == 403
    assert (await attribution_client.get(prefix + "/expense-attributions/" + command["request_key"])).status_code == 200
    assert (await attribution_client.get("/accounting/organizations/999/expense-attributions/" + command["request_key"])).status_code == 403


async def test_attribution_api_rejects_stale_preview_without_writing(attribution_client, db, book):
    prefix = f"/accounting/organizations/{book[0]}"
    headers = {"X-Expected-Principal": "tester"}
    catalog = await attribution_client.post(
        prefix + "/expense-catalog/commands",
        headers=headers,
        json={
            "request_key": str(uuid4()), "expected_revision": 0,
            "evidence": "Synthetic catalog", "action": "template",
        },
    )
    article_id = catalog.json()["result"]["articles"][0]["id"]
    line = await api_source(db, book)
    preview = await attribution_client.post(
        prefix + "/expense-attributions/preview",
        json={"source_line_id": line.id, "article_id": article_id, "effective_date": "2026-10-05"},
        headers=headers,
    )
    assert preview.status_code == 200
    command = {
        "request_key": str(uuid4()), "source_line_id": line.id, "article_id": article_id,
        "effective_date": "2026-10-05", "expected_basis_digest": "0" * 64,
        "evidence": "Проверен первичный документ", "explanation": "Проверка stale preview",
    }
    rejected = await attribution_client.post(prefix + "/expense-attributions", json=command, headers=headers)
    assert rejected.status_code == 409 and "Основание" in rejected.text
