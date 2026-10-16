from datetime import date

import pytest

from modules.accounting import reports


def document(direction="receipt", **changes):
    data = dict(source="bank-line-1", source_version=1, statement_reference="Statement1/line1",
                document_date="2026-09-01", operation_date="2026-09-01", posting_date="2026-09-01",
                policy_id=1, direction=direction, bank_account="51", settlement_account="62",
                amount="123.45", cash_activity="operating", explanation="Customer settlement")
    data.update(changes)
    return data


async def test_bank_receipt_preview_post_and_retry(client, db, book):
    prefix = f"/accounting/organizations/{book[0]}/bank"
    data = document(policy_id=book[1])
    preview = await client.post(prefix + "/preview", json=data)
    assert preview.status_code == 200
    assert [(line["account"], line["side"], line["amount"]) for line in preview.json()["lines"]] == [
        ("51", "debit", "123.45"), ("62", "credit", "123.45"),
    ]
    before = await reports.report(db, book[0], date(2026, 9, 1), date(2026, 9, 30))
    assert before["movements"] == []
    first = await client.post(prefix + "/confirm", json=data)
    second = await client.post(prefix + "/confirm", json=data)
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    reversed_direction = await client.post(prefix + "/confirm", json={**data, "direction": "payment"})
    assert reversed_direction.status_code == 422
    result = await reports.report(db, book[0], date(2026, 9, 1), date(2026, 9, 30))
    assert result["cashflow"]["closing"] == "123.45"
    assert result["pnl"]["profit"] == "0.00"


async def test_bank_payment_is_not_expense_by_itself(client, db, book):
    response = await client.post(f"/accounting/organizations/{book[0]}/bank/confirm", json=document(
        direction="payment", settlement_account="60", policy_id=book[1],
    ))
    assert response.status_code == 201
    result = await reports.report(db, book[0], date(2026, 9, 1), date(2026, 9, 30))
    assert result["cashflow"]["closing"] == "-123.45"
    assert result["pnl"]["profit"] == "0.00"


@pytest.mark.parametrize("changes", [
    {"amount": 1.1}, {"amount": "0.00"}, {"statement_reference": ""},
    {"bank_account": "41"}, {"settlement_account": "51"}, {"policy_id": 999},
    {"settlement_account": "90.1"},
    {"currency": "USD"}, {"cash_activity": "internal"},
    {"bank_dimensions": {"bank_statement": "different"}},
])
async def test_bank_rule_fails_closed(client, book, changes):
    data = document(policy_id=book[1])
    data.update(changes)
    response = await client.post(f"/accounting/organizations/{book[0]}/bank/preview", json=data)
    assert response.status_code == 422
