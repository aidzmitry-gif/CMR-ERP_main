from datetime import date

import pytest

from modules.accounting import bank_import, service
from modules.accounting.models import Organization, Policy, SourceBinding
from modules.finance.models import BankTransaction
from tests.accounting.test_fx_revaluation import _foreign_posting, _policy


async def configured_book(db, book):
    initial = await _policy(db, book[0])
    old = await db.get(Policy, initial)
    policy = Policy(
        organization_id=book[0], effective_from=date(2026, 3, 1),
        reference="Synthetic FX bank policy", inventory_method="specific", allocation_basis="direct_cost",
        depreciation_method="straight_line", normative_reference="Synthetic", normative_verified=True,
        approved_by="tester", currency_revaluation={**old.currency_revaluation,
            "settlement_allocation": "proportional_carrying", "settlement_rate_date": "posting_date"},
    )
    db.add(policy)
    await db.flush()
    receivable = _foreign_posting(policy.id, source="foreign-receivable")
    await service.post(db, book[0], receivable, "tester")
    await db.commit()
    return policy.id


async def source(db, org_id, *, direction="receipt", amount="40.00", on=date(2026, 9, 30), bound_org=None):
    row = BankTransaction(
        ext_id=f"FX-{direction}-{amount}-{on.isoformat()}-{bound_org or org_id}", direction=direction,
        source_provider="synthetic-bank", source_external_id=f"source-{direction}-{amount}",
        source_kind="api", source_reference="Synthetic immutable foreign bank source", occurred_on=on,
        amount=amount, currency="USD", account_code="USD-ACCOUNT", match_status="unmatched",
    )
    db.add(row)
    await db.flush()
    db.add(SourceBinding(organization_id=bound_org or org_id, source_type="finance_bank_transaction",
                         source_id=row.id, ownership="own", evidence="Synthetic ownership evidence", actor="tester"))
    await db.commit()
    return row


async def cash_position(db, book, policy_id, *, source="foreign-cash", negative=False):
    posting = _foreign_posting(policy_id, source=source)
    posting.lines[0].account = "51"
    posting.lines[0].cash_activity = "operating"
    if negative:
        posting.lines[0].side = "credit"
        posting.lines[1].account = "80"
        posting.lines[1].side = "debit"
    await service.post(db, book[0], posting, "tester")
    await db.commit()


def command(policy_id, row, *, settlement_account="62", posting_date="2026-09-30", rate_date="2026-09-30"):
    snapshot = bank_import.source_snapshot(row)
    return {
        "source_transaction_id": row.id, "source_digest": bank_import._digest(snapshot), "policy_id": policy_id,
        "posting_date": posting_date, "bank_account": "51", "bank_dimensions": {},
        "settlement_account": settlement_account, "settlement_dimensions": {},
        "rate": {"currency": "USD", "rate": "3.20", "rate_scale": 1,
                 "rate_date": rate_date, "rate_source": "Synthetic documented bank rate"},
    }


@pytest.mark.parametrize("direction,settlement_account,cash_after", [
    ("receipt", "62", "140.00"), ("payment", "60", "60.00"),
])
async def test_foreign_bank_preview_quotes_valid_receipt_or_payment(
    client, db, book, direction, settlement_account, cash_after):
    policy = await configured_book(db, book)
    await cash_position(db, book, policy, source=f"cash-{direction}")
    row = await source(db, book[0], direction=direction)
    response = await client.post(f"/accounting/organizations/{book[0]}/fx-bank-settlement/preview",
                                 json=command(policy, row, settlement_account=settlement_account))
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["posting_available"] is False
    assert result["cash"]["original_after"] == cash_after
    assert result["source_digest"] == command(policy, row)["source_digest"]
    assert result["basis"]["settlement_basis_digest"] == result["settlement"]["basis_digest"]
    assert result["basis"]["cash_basis_digest"]
    assert set(result["unavailable"]) == {"cash_valuation", "bank_posting", "foreign_source_import"}


async def test_foreign_bank_preview_rejects_source_from_other_organization(client, db, book):
    policy = await configured_book(db, book)
    await cash_position(db, book, policy)
    other = Organization(name="Other FX bank organization", unp="888888888")
    db.add(other)
    await db.commit()
    row = await source(db, book[0], bound_org=other.id, direction="receipt")
    response = await client.post(f"/accounting/organizations/{book[0]}/fx-bank-settlement/preview",
                                 json=command(policy, row))
    assert response.status_code == 422
    assert "binding" in response.json()["detail"]


async def test_foreign_bank_preview_blocks_direction_mismatch_and_insufficient_cash(client, db, book):
    policy = await configured_book(db, book)
    await cash_position(db, book, policy)
    receipt = await source(db, book[0], direction="receipt")
    mismatch = await client.post(f"/accounting/organizations/{book[0]}/fx-bank-settlement/preview",
                                 json=command(policy, receipt, settlement_account="60"))
    assert mismatch.status_code == 422
    assert "Receipt source" in mismatch.json()["detail"]
    payment = await source(db, book[0], direction="payment", amount="101.00")
    insufficient = await client.post(f"/accounting/organizations/{book[0]}/fx-bank-settlement/preview",
                                     json=command(policy, payment, settlement_account="60"))
    assert insufficient.status_code == 422
    assert "available positive foreign cash" in insufficient.json()["detail"]


async def test_foreign_bank_preview_blocks_excess_debt_and_date_mismatch(client, db, book):
    policy = await configured_book(db, book)
    await cash_position(db, book, policy)
    excess = await source(db, book[0], direction="receipt", amount="101.00")
    too_large = await client.post(f"/accounting/organizations/{book[0]}/fx-bank-settlement/preview",
                                  json=command(policy, excess))
    assert too_large.status_code == 422
    assert "exceeds" in too_large.json()["detail"]
    dated = await source(db, book[0], direction="receipt", amount="40.01", on=date(2026, 9, 29))
    mismatch = await client.post(f"/accounting/organizations/{book[0]}/fx-bank-settlement/preview",
                                 json=command(policy, dated, posting_date="2026-09-30"))
    assert mismatch.status_code == 422
    assert "date" in mismatch.json()["detail"]


async def test_foreign_bank_payment_blocks_negative_cash_position(client, db, book):
    policy = await configured_book(db, book)
    await cash_position(db, book, policy, negative=True)
    payment = await source(db, book[0], direction="payment")
    response = await client.post(f"/accounting/organizations/{book[0]}/fx-bank-settlement/preview",
                                 json=command(policy, payment, settlement_account="60"))
    assert response.status_code == 422
    assert "available positive foreign cash" in response.json()["detail"]
