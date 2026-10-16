"""Read-only financial transfer calculation; confirmation requires protected receipts."""
import hashlib
import json
from calendar import monthrange
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from modules.accounting.closing_policy import validate_accounts
from modules.accounting.models import (
    Entry,
    FinancialCloseReceipt,
    FinancialReopenItem,
    Line,
    Period,
    Policy,
)
from modules.accounting.schemas import FinancialClosingInput
from modules.accounting.service import AccountingError, lock_organization


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


async def preview(session, org_id, month, *, include_basis=False):
    from modules.accounting.closing_commands import authenticated_entries

    org = await lock_organization(session, org_id)
    technical = await authenticated_entries(session, org_id)
    first = date.fromisoformat(month + "-01")
    last = first.replace(day=monthrange(first.year, first.month)[1])
    policies = (await session.scalars(select(Policy).where(
        Policy.organization_id == org_id, Policy.effective_from <= last
    ).order_by(Policy.effective_from.desc()))).all()
    initial = next((p for p in policies if p.effective_from <= first), None)
    if initial is None or initial.financial_closing is None:
        raise AccountingError("Explicit financial closing policy must cover the whole month")
    applicable = [p for p in policies if p.effective_from > first] + [initial]
    if any(p.financial_closing != initial.financial_closing for p in applicable):
        raise AccountingError("Financial closing settings changed within this month; reconcile policy versions")
    settings = FinancialClosingInput.model_validate(initial.financial_closing)
    # Earlier active transfers were calculated under their own immutable policy.
    # Changing opening treatment/account roles cannot silently reinterpret them.
    active_closes = (await session.scalars(select(FinancialCloseReceipt).outerjoin(FinancialReopenItem,
        FinancialReopenItem.close_receipt_id == FinancialCloseReceipt.id).where(
        FinancialCloseReceipt.organization_id == org_id, FinancialCloseReceipt.month < month,
        FinancialReopenItem.id.is_(None)))).all()
    for receipt in active_closes:
        previous_policy = await session.get(Policy, receipt.snapshot["preview"]["policy_id"])
        previous_settings = FinancialClosingInput.model_validate(previous_policy.financial_closing)
        if previous_settings.model_dump(exclude={"reference"}) != settings.model_dump(exclude={"reference"}):
            raise AccountingError("Financial closing policy changed since an active close; reopen and reconcile the transition")
    accounts = await validate_accounts(session, org_id, last, settings)
    codes = {*settings.monthly_accounts, settings.result_account, settings.retained_earnings_account}
    if any(accounts[code].currency_tracking for code in codes):
        raise AccountingError("Currency-tracked closing accounts require a supported currency transfer rule")
    period = await session.scalar(select(Period).where(Period.organization_id == org_id, Period.month == month)
                                  .execution_options(populate_existing=True))
    if period and period.closed:
        raise AccountingError("Reopen the period before calculating a new financial transfer")
    rows = (await session.execute(select(Entry, Line).join(Line, Line.entry_id == Entry.id).where(
        Entry.organization_id == org_id, Entry.posting_date <= last,
        Line.account_code.in_(codes),
    ).order_by(Entry.id, Line.id))).all()
    balances = {}
    source = []
    for entry, line in rows:
        if entry.operation in {"period_close", "period_reopen"} and entry.id not in technical:
            raise AccountingError("Historical technical transfers require a verified financial receipt")
        source.append({"entry_id": entry.id, "entry_digest": entry.digest, "line_id": line.id,
            "account_id": line.account_id, "account_code": line.account_code,
            "category": line.category, "cash": line.cash, "side": line.side,
            "amount": str(line.amount), "dimensions": line.dimensions,
            "currency": line.currency, "quantity": str(line.quantity) if line.quantity is not None else None,
            "opening": entry.opening, "posting_date": entry.posting_date.isoformat()})
        if entry.opening and settings.opening_balance_treatment == "exclude":
            continue
        account = accounts[line.account_code]
        if (line.category != account.category or line.cash or line.currency != "BYN"
                or line.quantity is not None or not set(account.required_dimensions).issubset(line.dimensions)):
            raise AccountingError(f"Historical closing account {line.account_code} needs reconciliation")
        key = (line.account_code, canonical(line.dimensions))
        balances[key] = balances.get(key, Decimal("0")) + (line.amount if line.side == "debit" else -line.amount)
    monthly, annual = [], []

    def transfer(target, code, dimensions_json, balance, recipient, recipient_dimensions):
        if not balance:
            return
        amount = format(abs(balance), ".2f")
        target.append({"account": code, "dimensions": json.loads(dimensions_json),
                       "side": "credit" if balance > 0 else "debit", "amount": amount})
        target.append({"account": recipient, "dimensions": recipient_dimensions,
                       "side": "debit" if balance > 0 else "credit", "amount": amount})

    result_balances = {dims: amount for (code, dims), amount in balances.items() if code == settings.result_account}
    result_dims = canonical(settings.result_dimensions)
    for (code, dimensions), balance in sorted(balances.items()):
        if code in settings.monthly_accounts:
            transfer(monthly, code, dimensions, balance, settings.result_account, settings.result_dimensions)
            result_balances[result_dims] = result_balances.get(result_dims, Decimal("0")) + balance
    if first.month == settings.year_end_month:
        for dimensions, balance in sorted(result_balances.items()):
            transfer(annual, settings.result_account, dimensions, balance,
                     settings.retained_earnings_account, settings.retained_dimensions)
    basis = {"organization_id": org_id, "month": month, "organization_generation": org.generation,
        "period_generation": period.generation if period else 0,
        "policies": [{"id": p.id, "effective_from": p.effective_from.isoformat(),
                      "normative_verified": p.normative_verified, "settings": p.financial_closing} for p in applicable],
        "accounts": [{"id": accounts[code].id, "code": code, "category": accounts[code].category,
                      "dimensions": accounts[code].required_dimensions} for code in sorted(codes)],
        "source_lines": source, "monthly_lines": monthly, "annual_lines": annual}
    result = {"organization_id": org_id, "month": month, "policy_id": policies[0].id,
        "period_generation": basis["period_generation"],
        "basis_digest": hashlib.sha256(canonical(basis).encode()).hexdigest(),
        "source_line_count": len(source), "monthly_lines": monthly, "annual_lines": annual,
        "normative_verified": all(p.normative_verified for p in applicable),
        "confirmation_available": False, "status": "preview_only"}
    if include_basis:
        result["basis"] = basis
    return result
