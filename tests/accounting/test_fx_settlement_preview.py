from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from modules.accounting import fx_revaluation, service
from modules.accounting.models import Entry, Policy
from modules.accounting.schemas import FxRevaluationConfirmInput, FxRevaluationInput
from tests.accounting.test_fx_revaluation import _foreign_posting, _policy


async def setup_position(db, book, configured=True):
    initial = await _policy(db, book[0])
    if configured:
        old = await db.get(Policy, initial)
        row = Policy(organization_id=book[0], effective_from=date(2026, 3, 1),
            reference="Synthetic settlement policy", inventory_method="specific", allocation_basis="direct_cost",
            depreciation_method="straight_line", normative_reference="Synthetic", normative_verified=True,
            approved_by="tester", currency_revaluation={**old.currency_revaluation,
                "settlement_allocation": "proportional_carrying", "settlement_rate_date": "posting_date"})
        db.add(row)
        await db.flush()
        initial = row.id
    await service.post(db, book[0], _foreign_posting(initial), "tester")
    await db.commit()
    return initial


def command(policy, account="62", amount="40.00"):
    return {"policy_id": policy, "posting_date": "2026-09-30", "account": account,
            "dimensions": {}, "amount": amount, "rate": {"currency": "USD", "rate": "3.20",
                "rate_scale": 1, "rate_date": "2026-09-30", "rate_source": "Synthetic reviewed rate"}}


@pytest.mark.parametrize("account,amount,allocated,documentary,result_account,result_side", [
    ("62", "40.00", "120", "128", "91.1", "credit"),
    ("60", "40.00", "120", "128", "91.2", "debit"),
    ("62", "100.00", "300", "320", "91.1", "credit"),
])
async def test_partial_or_full_settlement_is_valued_without_posting(
        client, db, book, account, amount, allocated, documentary, result_account, result_side):
    from decimal import Decimal
    policy = await setup_position(db, book)
    count = await db.scalar(select(func.count()).select_from(Entry))
    response = await client.post(f"/accounting/organizations/{book[0]}/fx-settlement/preview",
                                 json=command(policy, account, amount))
    assert response.status_code == 200, response.text
    result = response.json()
    assert Decimal(result["allocated_book_amount"]) == Decimal(allocated)
    assert Decimal(result["documentary_amount"]) == Decimal(documentary)
    assert (result["difference_account"], result["difference_side"]) == (result_account, result_side)
    assert result["posting_available"] is False
    assert await db.scalar(select(func.count()).select_from(Entry)) == count


@pytest.mark.parametrize("configured,amount", [(False, "40.00"), (True, "101.00")])
async def test_missing_method_or_excess_payment_is_blocked(client, db, book, configured, amount):
    policy = await setup_position(db, book, configured)
    response = await client.post(f"/accounting/organizations/{book[0]}/fx-settlement/preview",
                                 json=command(policy, amount=amount))
    assert response.status_code == 422


async def test_partial_allocation_includes_prior_revaluation(client, db, book):
    from decimal import Decimal
    policy = await setup_position(db, book)
    revalue = FxRevaluationInput(request_key=uuid4(), policy_id=policy, posting_date=date(2026, 9, 30),
        expected_generation=1, rates=[command(policy)["rate"]], evidence="Synthetic valuation before settlement")
    plan = await fx_revaluation.preview(db, book[0], "2026-09", revalue)
    await fx_revaluation.confirm(db, book[0], "2026-09", FxRevaluationConfirmInput(
        **revalue.model_dump(), basis_digest=plan["basis_digest"], digest=plan["digest"]), "tester")
    await db.commit()
    body = command(policy, amount="50.00")
    body["rate"]["rate"] = "3.40"
    response = await client.post(f"/accounting/organizations/{book[0]}/fx-settlement/preview", json=body)
    assert response.status_code == 200, response.text
    result = response.json()
    assert Decimal(result["allocated_book_amount"]) == Decimal("160.00")
    assert Decimal(result["documentary_amount"]) == Decimal("170.00")
    assert Decimal(result["exchange_difference"]) == Decimal("10.00")
    assert result["basis"]["prior_valuations"]
