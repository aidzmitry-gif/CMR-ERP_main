"""Local contract tests for the explicit FX revaluation workflow.

The fixtures are synthetic and prove the review/idempotency boundary only; they
do not certify a Belarus statutory rate source.
"""
from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import select

from modules.accounting import fx_revaluation, service
from modules.accounting.models import Account, Entry, FxRevaluationReceipt, Policy
from modules.accounting.schemas import (
    CurrencyRevaluationPolicyInput,
    FxRevaluationConfirmInput,
    FxRevaluationInput,
    LineInput,
    PostingInput,
)


async def _policy(db, org_id):
    db.add_all([
        Account(organization_id=org_id, code="91.1", title="Synthetic FX gain", category="income",
                valid_from=date(2026, 1, 1), required_dimensions=[], currency_tracking=False,
                quantity_tracking=False, cash=False, normative_ref="Synthetic"),
        Account(organization_id=org_id, code="91.2", title="Synthetic FX loss", category="expense",
                valid_from=date(2026, 1, 1), required_dimensions=[], currency_tracking=False,
                quantity_tracking=False, cash=False, normative_ref="Synthetic"),
    ])
    row = Policy(
        organization_id=org_id, effective_from=date(2026, 2, 1),
        reference="Synthetic FX policy", inventory_method="specific",
        allocation_basis="direct_cost", depreciation_method="straight_line",
        normative_reference="Synthetic only", normative_verified=True,
        currency_revaluation={
            "monetary_accounts": ["62", "60"], "gain_account": "91.1", "loss_account": "91.2",
            "gain_dimensions": {}, "loss_dimensions": {}, "reference": "Synthetic reviewed FX instruction",
        }, approved_by="tester",
    )
    db.add(row)
    await db.commit()
    return row.id


def _foreign_posting(policy_id, *, amount="300.00", original="100.00", source="foreign-sale"):
    def line(account, side):
        return LineInput(
            account=account, side=side, amount=amount, currency="USD", original_amount=original,
            rate="3.00", rate_scale=1, rate_date=date(2026, 9, 30), rate_source="Synthetic source rate",
        )
    return PostingInput(
        source=source, source_version=1, operation="manual", document_date=date(2026, 9, 30),
        operation_date=date(2026, 9, 30), posting_date=date(2026, 9, 30), policy_id=policy_id,
        rule_version="synthetic-v1", explanation="Synthetic foreign-currency transaction",
        lines=[line("62", "debit"), line("60", "credit")],
    )


@pytest.mark.parametrize("rate,delta,asset_side,liability_side", [
    ("3.20", "20.00", "debit", "credit"),
    ("2.80", "-20.00", "credit", "debit"),
])
async def test_preview_requires_explicit_policy_and_builds_balanced_adjustment(
        db, book, rate, delta, asset_side, liability_side):
    policy_id = await _policy(db, book[0])
    await service.post(db, book[0], _foreign_posting(policy_id), "tester")
    await db.commit()
    plan = await fx_revaluation.preview(db, book[0], "2026-09", FxRevaluationInput(
        request_key=uuid4(), policy_id=policy_id, posting_date=date(2026, 9, 30),
        expected_generation=1, rates=[{
            "currency": "USD", "rate": rate, "rate_scale": 1,
            "rate_date": "2026-09-30", "rate_source": "Synthetic central-bank evidence",
        }], evidence="Synthetic reviewed rate evidence",
    ))
    deltas = {row["account"]: row["delta"] for row in plan["adjustments"]}
    from decimal import Decimal
    assert deltas == {"60": str(-Decimal(delta)), "62": delta}
    adjustments = {row["account"]: row for row in plan["adjustments"]}
    assert adjustments["60"]["monetary_side"] == liability_side
    assert adjustments["62"]["monetary_side"] == asset_side
    assert adjustments["60"]["counterpart"] == ("91.2" if liability_side == "credit" else "91.1")
    assert adjustments["62"]["counterpart"] == ("91.1" if asset_side == "debit" else "91.2")
    assert len(plan["posting_document"]["lines"]) == 4
    assert sum(
        (Decimal(line["amount"]) if line["side"] == "debit" else -Decimal(line["amount"])
         for line in plan["posting_document"]["lines"]),
        start=Decimal("0"),
    ) == Decimal("0")
    assert plan["confirmation_available"] is True
    assert plan["statutory_certified"] is False


async def test_confirm_is_atomic_and_replayable(db, book):
    policy_id = await _policy(db, book[0])
    await service.post(db, book[0], _foreign_posting(policy_id), "tester")
    await db.commit()
    command = FxRevaluationInput(
        request_key=uuid4(), policy_id=policy_id, posting_date=date(2026, 9, 30),
        expected_generation=1, rates=[{
            "currency": "USD", "rate": "3.20", "rate_scale": 1,
            "rate_date": "2026-09-30", "rate_source": "Synthetic central-bank evidence",
        }], evidence="Synthetic reviewed rate evidence",
    )
    plan = await fx_revaluation.preview(db, book[0], "2026-09", command)
    confirm = FxRevaluationConfirmInput(
        **command.model_dump(), basis_digest=plan["basis_digest"], digest=plan["digest"],
    )
    receipt = await fx_revaluation.confirm(db, book[0], "2026-09", confirm, "tester")
    await db.commit()
    assert receipt.entry_id is not None
    assert (await fx_revaluation.confirm(db, book[0], "2026-09", confirm, "tester")).id == receipt.id
    assert await db.scalar(select(Entry.operation).where(Entry.id == receipt.entry_id)) == "fx_revaluation"
    assert await db.scalar(select(FxRevaluationReceipt.organization_id).where(
        FxRevaluationReceipt.id == receipt.id)) == book[0]


async def test_generic_posting_cannot_create_fx_revaluation(db, book):
    policy_id = await _policy(db, book[0])
    posting = _foreign_posting(policy_id)
    posting.operation = "fx_revaluation"
    with pytest.raises(service.AccountingError, match="dedicated"):
        await service.post(db, book[0], posting, "tester")


async def test_rates_are_explicit_and_unknown_currency_is_rejected(db, book):
    policy_id = await _policy(db, book[0])
    command = FxRevaluationInput(
        request_key=uuid4(), policy_id=policy_id, posting_date=date(2026, 9, 30),
        expected_generation=0, rates=[{
            "currency": "EUR", "rate": "3.20", "rate_scale": 1,
            "rate_date": "2026-09-30", "rate_source": "Synthetic central-bank evidence",
        }], evidence="Synthetic reviewed rate evidence",
    )
    with pytest.raises(service.AccountingError, match="Unknown or inactive"):
        await fx_revaluation.preview(db, book[0], "2026-09", command)


async def test_existing_foreign_history_requires_a_rate_for_each_currency(db, book):
    policy_id = await _policy(db, book[0])
    await service.post(db, book[0], _foreign_posting(policy_id), "tester")
    await db.commit()
    command = FxRevaluationInput(
        request_key=uuid4(), policy_id=policy_id, posting_date=date(2026, 9, 30),
        expected_generation=1, rates=[{
            "currency": "RUB", "rate": "3.20", "rate_scale": 1,
            "rate_date": "2026-09-30", "rate_source": "Synthetic central-bank evidence",
        }], evidence="Synthetic reviewed rate evidence",
    )
    with pytest.raises(service.AccountingError, match="explicit FX rate is required for USD"):
        await fx_revaluation.preview(db, book[0], "2026-09", command)


async def test_policy_validation_rejects_non_currency_tracked_account(db, book):
    db.add(Account(organization_id=book[0], code="90.5", title="Synthetic non-FX income",
                   category="income", valid_from=date(2026, 1, 1), required_dimensions=[],
                   currency_tracking=False, quantity_tracking=False, cash=False, normative_ref="Synthetic"))
    db.add(Account(organization_id=book[0], code="91.2", title="Synthetic FX loss", category="expense",
                   valid_from=date(2026, 1, 1), required_dimensions=[], currency_tracking=False,
                   quantity_tracking=False, cash=False, normative_ref="Synthetic"))
    db.add(Account(organization_id=book[0], code="91.1", title="Synthetic FX gain", category="income",
                   valid_from=date(2026, 1, 1), required_dimensions=[], currency_tracking=False,
                   quantity_tracking=False, cash=False, normative_ref="Synthetic"))
    await db.commit()
    with pytest.raises(service.AccountingError, match="Currency revaluation account"):
        await fx_revaluation.validate_policy(db, book[0], date(2026, 1, 1),
            CurrencyRevaluationPolicyInput(
                monetary_accounts=["90.5"], gain_account="91.1", loss_account="91.2",
                gain_dimensions={}, loss_dimensions={}, reference="Synthetic reviewed FX instruction"))
