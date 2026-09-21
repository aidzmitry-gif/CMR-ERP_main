"""Local contract tests for the explicit FX revaluation workflow.

The fixtures are synthetic and prove the review/idempotency boundary only; they
do not certify a Belarus statutory rate source.
"""
from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import select, update

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


async def test_unverified_policy_blocks_new_confirmation_but_not_existing_replay(db, book):
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
    await db.execute(update(Policy).where(Policy.id == policy_id).values(normative_verified=False))
    await db.commit()
    blocked_plan = await fx_revaluation.preview(db, book[0], "2026-09", command)
    blocked_confirm = FxRevaluationConfirmInput(
        **command.model_dump(), basis_digest=blocked_plan["basis_digest"], digest=blocked_plan["digest"],
    )
    assert blocked_plan["confirmation_available"] is False
    with pytest.raises(service.AccountingError, match="normatively verified policy"):
        await fx_revaluation.confirm(db, book[0], "2026-09", blocked_confirm, "tester")
    assert await db.scalar(select(Entry.id).where(Entry.operation == "fx_revaluation")) is None
    assert await db.scalar(select(FxRevaluationReceipt.id)) is None

    await db.execute(update(Policy).where(Policy.id == policy_id).values(normative_verified=True))
    await db.commit()
    approved_plan = await fx_revaluation.preview(db, book[0], "2026-09", command)
    approved_confirm = FxRevaluationConfirmInput(
        **command.model_dump(), basis_digest=approved_plan["basis_digest"], digest=approved_plan["digest"],
    )
    receipt = await fx_revaluation.confirm(db, book[0], "2026-09", approved_confirm, "tester")
    await db.commit()
    await db.execute(update(Policy).where(Policy.id == policy_id).values(normative_verified=False))
    await db.commit()
    assert (await fx_revaluation.confirm(db, book[0], "2026-09", approved_confirm, "tester")).id == receipt.id


async def test_revaluation_uses_prior_adjustments_and_noop_keeps_correction_chain(db, book):
    policy_id = await _policy(db, book[0])
    await service.post(db, book[0], _foreign_posting(policy_id), "tester")
    await db.commit()

    async def calculate(rate, on):
        month = on.strftime("%Y-%m")
        period = await service.period_for(db, book[0], month)
        command = FxRevaluationInput(request_key=uuid4(), policy_id=policy_id, posting_date=on,
            expected_generation=period.generation, rates=[{
                "currency": "USD", "rate": rate, "rate_scale": 1,
                "rate_date": on, "rate_source": "Synthetic rate",
            }], evidence="Synthetic repeated valuation")
        plan = await fx_revaluation.preview(db, book[0], month, command)
        receipt = await fx_revaluation.confirm(db, book[0], month, FxRevaluationConfirmInput(
            **command.model_dump(), basis_digest=plan["basis_digest"], digest=plan["digest"]), "tester")
        await db.commit()
        return plan, receipt

    first, first_receipt = await calculate("3.20", date(2026, 9, 30))
    unchanged, noop_receipt = await calculate("3.20", date(2026, 9, 30))
    assert unchanged["adjustments"] == []
    assert noop_receipt.entry_id is None
    corrected, corrected_receipt = await calculate("3.30", date(2026, 9, 30))
    assert corrected["posting_document"]["correction_of"] == first_receipt.entry_id
    assert {row["account"]: row["delta"] for row in corrected["adjustments"]} == {"60": "-10.00", "62": "10.00"}
    following, _ = await calculate("3.40", date(2026, 10, 31))
    assert {row["account"]: row["book_balance"] for row in following["adjustments"]} == {"60": "-330.00", "62": "330.00"}
    assert {row["account"]: row["delta"] for row in following["adjustments"]} == {"60": "-10.00", "62": "10.00"}
    assert corrected_receipt.entry_id != first_receipt.entry_id


async def test_generic_posting_cannot_create_fx_revaluation(db, book):
    policy_id = await _policy(db, book[0])
    posting = _foreign_posting(policy_id)
    posting.operation = "fx_revaluation"
    with pytest.raises(service.AccountingError, match="dedicated"):
        await service.post(db, book[0], posting, "tester")


async def test_unattributed_byn_correction_of_foreign_source_is_blocked(db, book):
    policy_id = await _policy(db, book[0])
    original = await service.post(db, book[0], _foreign_posting(policy_id), "tester")
    correction = _foreign_posting(policy_id, source="synthetic-correction")
    correction.correction_of = original.id
    correction.lines = [LineInput(account="62", side="credit", amount="20.00"),
                        LineInput(account="91.2", side="debit", amount="20.00")]
    await service.post(db, book[0], correction, "tester")
    await db.commit()
    command = FxRevaluationInput(request_key=uuid4(), policy_id=policy_id,
        posting_date=date(2026, 9, 30), expected_generation=2, rates=[{
            "currency": "USD", "rate": "3.20", "rate_scale": 1,
            "rate_date": "2026-09-30", "rate_source": "Synthetic rate",
        }], evidence="Synthetic mixed valuation evidence")
    with pytest.raises(service.AccountingError, match="unattributed BYN correction"):
        await fx_revaluation.preview(db, book[0], "2026-09", command)


async def test_previous_wrong_liability_side_uses_actual_ledger_not_intended_delta(db, book, monkeypatch):
    policy_id = await _policy(db, book[0])
    await service.post(db, book[0], _foreign_posting(policy_id), "tester")
    await db.commit()
    command = FxRevaluationInput(request_key=uuid4(), policy_id=policy_id,
        posting_date=date(2026, 9, 30), expected_generation=1, rates=[{
            "currency": "USD", "rate": "3.20", "rate_scale": 1,
            "rate_date": "2026-09-30", "rate_source": "Synthetic historical rate",
        }], evidence="Synthetic old sign behavior")
    # Reproduce the former liability double inversion without editing a posted entry.
    with monkeypatch.context() as historical:
        historical.setattr(fx_revaluation, "_side", lambda delta: "debit")
        historical.setattr(fx_revaluation, "_counterpart", lambda delta, gain, loss: (gain, "credit"))
        plan = await fx_revaluation.preview(db, book[0], "2026-09", command)
        receipt = await fx_revaluation.confirm(db, book[0], "2026-09", FxRevaluationConfirmInput(
            **command.model_dump(), basis_digest=plan["basis_digest"], digest=plan["digest"]), "tester")
        await db.commit()
    old_digest = receipt.digest
    new_command = command.model_copy(update={"request_key": uuid4(), "expected_generation": 2})
    repaired = await fx_revaluation.preview(db, book[0], "2026-09", new_command)
    assert len(repaired["adjustments"]) == 1
    adjustment = repaired["adjustments"][0]
    assert (adjustment["account"], adjustment["book_balance"], adjustment["delta"], adjustment["monetary_side"]) == (
        "60", "-280.00", "-40.00", "credit")
    assert receipt.digest == old_digest
    # Corrupt evidence must block further calculation, never be ignored.
    await db.execute(update(FxRevaluationReceipt).where(FxRevaluationReceipt.id == receipt.id)
                     .values(snapshot={**receipt.snapshot, "adjustments": []}))
    with pytest.raises(service.AccountingError, match="missing or damaged"):
        await fx_revaluation.preview(db, book[0], "2026-09", new_command)


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
