"""Read-only valuation of an explicitly selected monetary settlement position.

This is not bank posting and does not allocate a payment or write ledger lines.
"""
from datetime import date
from decimal import Decimal
from fractions import Fraction

from pydantic import Field
from sqlalchemy import select

from core.domain.reference import Currency
from modules.accounting import fx_revaluation as fx
from modules.accounting import service
from modules.accounting.models import Entry, Line, Policy
from modules.accounting.schemas import (
    Code,
    CurrencyRevaluationPolicyInput,
    FxRateInput,
    Input,
    Money,
)


class SettlementPreviewInput(Input):
    policy_id: int = Field(gt=0, strict=True)
    posting_date: date
    account: Code
    dimensions: dict[str, str] = Field(default_factory=dict)
    amount: Money
    rate: FxRateInput


async def preview(session, org_id, data: SettlementPreviewInput):
    org = await service.lock_organization(session, org_id)
    policy = await session.scalar(select(Policy).where(
        Policy.organization_id == org_id, Policy.effective_from <= data.posting_date,
    ).order_by(Policy.effective_from.desc(), Policy.id.desc()).limit(1))
    if policy is None or policy.id != data.policy_id or not policy.normative_verified or not policy.currency_revaluation:
        raise service.AccountingError("An effective approved currency policy is required")
    settings = CurrencyRevaluationPolicyInput.model_validate(policy.currency_revaluation)
    if settings.settlement_allocation is None or settings.settlement_rate_date is None:
        raise service.AccountingError("Set explicit settlement allocation and rate-date methods in the policy")
    if data.amount <= 0 or data.rate.currency == "BYN" or data.rate.rate_date != data.posting_date:
        raise service.AccountingError("A positive foreign amount and documented posting-date rate are required")
    if await session.scalar(select(Currency.code).where(
        Currency.code == data.rate.currency, Currency.is_active.is_(True),
    )) is None:
        raise service.AccountingError("Unknown or inactive settlement currency")
    _, accounts, gain, loss = await fx.validate_policy_accounts(session, org_id, data.posting_date, settings)
    account = next((row for row in accounts if row.code == data.account), None)
    dimensions = fx._dimensions(data.dimensions, label="Settlement position")
    if account is None or not set(account.required_dimensions).issubset(dimensions):
        raise service.AccountingError("Select a policy monetary account and its required analytics")
    rows = (await session.execute(select(Entry, Line).join(Line, Line.entry_id == Entry.id).where(
        Entry.organization_id == org_id, Entry.posting_date <= data.posting_date,
        Line.account_code == data.account, Line.currency == data.rate.currency,
    ).order_by(Entry.id, Line.id))).all()
    rows = [(entry, line) for entry, line in rows if line.dimensions == dimensions]
    original, carrying = Decimal("0"), Decimal("0")
    evidence = []
    for entry, line in rows:
        if line.original_amount is None:
            raise service.AccountingError("Foreign monetary history is missing its original amount")
        sign = 1 if line.side == "debit" else -1
        original += sign * line.original_amount
        carrying += sign * line.amount
        evidence.append({"entry_id": entry.id, "entry_digest": entry.digest, "line_id": line.id,
                         "side": line.side, "original_amount": str(line.original_amount), "amount": str(line.amount)})
    key = (data.account, fx._canonical(dimensions), data.rate.currency)
    balances = {key: {"book": carrying, "line_ids": [line.id for _, line in rows]}}
    valuations = await fx._prior_valuations(session, org_id, data.posting_date, balances, {entry.id for entry, _ in rows})
    carrying = balances[key]["book"]
    if original == 0 or data.amount > abs(original) or original * carrying < 0:
        raise service.AccountingError("Settlement exceeds the monetary position or its carrying balance is inconsistent")
    # Full settlement consumes the exact remaining cents; partial allocation is
    # rational arithmetic under the explicit saved proportional method.
    allocated = abs(carrying) if data.amount == abs(original) else fx._round_cents(
        Fraction(abs(carrying)) * Fraction(data.amount) * 100 / Fraction(abs(original)))
    documentary = fx._converted(data.amount, data.rate.rate, data.rate.rate_scale)
    difference = documentary - allocated
    signed_difference = difference if original > 0 else -difference
    counterpart, side = fx._counterpart(signed_difference, gain, loss)
    basis = {"organization_id": org_id, "organization_generation": org.generation,
             "policy_id": policy.id, "policy": settings.model_dump(mode="json"),
             "account_versions": [{"id": row.id, "code": row.code,
                 "valid_from": row.valid_from.isoformat(), "category": row.category,
                 "required_dimensions": row.required_dimensions,
                 "currency_tracking": row.currency_tracking,
                 "quantity_tracking": row.quantity_tracking, "cash": row.cash}
                 for row in sorted([account, gain, loss], key=lambda item: item.code)],
             "input": data.model_dump(mode="json"), "source_lines": evidence,
             "prior_valuations": valuations}
    return {"status": "preview_only", "posting_available": False, "basis_digest": fx._digest(basis),
            "basis": basis, "original_balance": str(original), "book_balance": str(carrying),
            "allocated_book_amount": str(allocated), "documentary_amount": str(documentary),
            "exchange_difference": str(difference),
            "difference_account": counterpart.code if difference else None,
            "difference_side": side if difference else None,
            "remaining_original": str(abs(original) - data.amount),
            "remaining_book_amount": str(abs(carrying) - allocated)}
