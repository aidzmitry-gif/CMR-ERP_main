"""Read-only foreign-currency cash position for a future bank-payment workflow.

This helper deliberately has no payment, posting, rate selection, or valuation
behaviour.  It reports only the immutable ledger position as of one date.
"""
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from core.domain.reference import Currency
from modules.accounting import fx_revaluation as fx
from modules.accounting import service
from modules.accounting.models import Entry, Line


async def position(session, org_id: int, *, as_of: date, account_code: str,
                   dimensions: dict[str, str], currency: str) -> dict:
    """Return a dated cash position without guessing rates or analytics.

    A BYN line on the selected foreign-currency cash position cannot currently
    be attributed to a documented cash valuation receipt.  Reject it rather
    than silently mixing it into carrying value.
    """
    if not isinstance(currency, str) or len(currency) != 3 or currency != currency.upper() or currency == "BYN":
        raise service.AccountingError("Cash position requires one explicit non-BYN currency")
    if await session.scalar(select(Currency.code).where(
        Currency.code == currency, Currency.is_active.is_(True),
    )) is None:
        raise service.AccountingError("Cash position currency is unknown or inactive")
    requested_dimensions = fx._dimensions(dimensions, label="Cash position analytics")
    org = await service.lock_organization(session, org_id)
    account = (await service.accounts_on(session, org_id, as_of)).get(account_code)
    if account is None or not account.cash or not account.currency_tracking or account.category != "asset":
        raise service.AccountingError("Cash position account must be an effective cash currency-tracked asset")
    if account.quantity_tracking:
        raise service.AccountingError("Cash position account cannot use quantity tracking")
    if set(account.required_dimensions) != set(requested_dimensions):
        raise service.AccountingError(f"Cash position account {account.code} requires its exact analytics")

    rows = (await session.execute(select(Entry, Line).join(Line, Line.entry_id == Entry.id).where(
        Entry.organization_id == org_id, Entry.posting_date <= as_of,
        Line.account_code == account.code,
    ).order_by(Entry.id, Line.id))).all()
    original = Decimal("0")
    carrying = Decimal("0")
    source_lines = []
    for entry, line in rows:
        if line.dimensions != requested_dimensions:
            continue
        if line.currency == "BYN":
            raise service.AccountingError(
                "Cash position has an unsupported BYN movement; documented cash valuation-only records are required"
            )
        if line.currency != currency:
            continue
        if line.original_amount is None:
            raise service.AccountingError("Cash foreign-currency history is missing its original amount")
        sign = Decimal("1") if line.side == "debit" else Decimal("-1")
        original += sign * line.original_amount
        carrying += sign * line.amount
        source_lines.append({
            "entry_id": entry.id, "entry_digest": entry.digest,
            "posting_date": entry.posting_date.isoformat(), "line_id": line.id,
            "account_id": line.account_id, "side": line.side,
            "currency": line.currency, "original_amount": str(line.original_amount),
            "amount": str(line.amount), "dimensions": line.dimensions,
            "rate": str(line.rate) if line.rate is not None else None,
            "rate_scale": line.rate_scale,
            "rate_date": line.rate_date.isoformat() if line.rate_date else None,
            "rate_source": line.rate_source,
        })
    account_version = {
        "id": account.id, "code": account.code, "valid_from": account.valid_from.isoformat(),
        "category": account.category, "required_dimensions": account.required_dimensions,
        "currency_tracking": account.currency_tracking, "quantity_tracking": account.quantity_tracking,
        "cash": account.cash,
    }
    basis = {
        "organization_id": org_id, "organization_generation": org.generation,
        "as_of": as_of.isoformat(),
        "input": {"account": account_code, "dimensions": requested_dimensions, "currency": currency},
        "account_versions": [account_version], "source_lines": source_lines,
    }
    return {
        "status": "preview_only", "posting_available": False, "basis_digest": fx._digest(basis),
        "basis": basis, "original_balance": str(original), "book_balance": str(carrying),
    }
