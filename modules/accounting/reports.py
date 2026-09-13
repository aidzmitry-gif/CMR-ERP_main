"""Reproducible reports from immutable lines, not present-day payment statuses."""
from __future__ import annotations

import json
from calendar import monthrange
from collections import defaultdict
from decimal import Decimal

from sqlalchemy import select

from modules.accounting.models import Entry, Inbox, Line, Period, SourceControl
from modules.accounting.service import AccountingError, lock_organization


def money(value):
    return format(value, ".2f")


async def report(session, org_id, start, end):
    from modules.accounting.closing_commands import authenticated_entries

    if end < start:
        raise AccountingError("End precedes start")
    # Hold the same lock as all ledger/period writers for one coherent report.
    # A multi-query READ COMMITTED report must not mix old amounts with a new close.
    await lock_organization(session, org_id)
    technical = await authenticated_entries(session, org_id)
    rows = (await session.execute(select(Entry, Line).join(Line, Line.entry_id == Entry.id).where(
        Entry.organization_id == org_id, Entry.posting_date <= end
    ).order_by(Entry.posting_date, Entry.id, Line.id))).all()
    trial = {}
    balances = defaultdict(lambda: Decimal("0"))
    pnl = defaultdict(lambda: Decimal("0"))
    cash = defaultdict(lambda: Decimal("0"))
    movements = []
    opening_movements = []
    for entry, line in rows:
        if entry.operation in {"period_close", "period_reopen"} and entry.id not in technical:
            raise AccountingError("Technical financial entry has no verified receipt")
        signed = line.amount if line.side == "debit" else -line.amount
        key = (line.account_code, json.dumps(line.dimensions, sort_keys=True), line.currency)
        bucket = trial.setdefault(key, {
            "account": line.account_code, "title": line.account_title,
            "dimensions": line.dimensions, "currency": line.currency,
            "off_balance": line.category == "off_balance",
            "opening": Decimal("0"), "debit": Decimal("0"), "credit": Decimal("0"),
            "original_opening": Decimal("0"), "original_debit": Decimal("0"),
            "original_credit": Decimal("0"), "quantity_opening": Decimal("0"),
            "quantity_debit": Decimal("0"), "quantity_credit": Decimal("0"),
        })
        before = entry.posting_date < start or (entry.opening and entry.posting_date <= start)
        column = "opening" if before else line.side
        sign = -1 if before and line.side == "credit" else 1
        bucket[column] += sign * line.amount
        bucket["original_" + column] += sign * (line.original_amount or Decimal("0"))
        bucket["quantity_" + column] += sign * (line.quantity or Decimal("0"))
        balances[line.category] += signed
        if entry.id not in technical and not before and not entry.opening and line.category in {"income", "expense"}:
            pnl[line.category] += signed
        (opening_movements if before else movements).append({
                "entry_id": entry.id, "source": entry.source, "date": str(entry.posting_date),
                "account": line.account_code, "title": line.account_title,
                "line_id": line.id, "currency": line.currency,
                "side": line.side, "amount": money(line.amount), "dimensions": line.dimensions,
            })
        if line.cash:
            cash["opening" if before else "movement"] += signed
            if not before:
                cash[line.cash_activity or "unclassified"] += signed
    for bucket in trial.values():
        for prefix in ("", "original_", "quantity_"):
            bucket[prefix + "closing"] = (
                bucket[prefix + "opening"] + bucket[prefix + "debit"] - bucket[prefix + "credit"]
            )
        for key, value in list(bucket.items()):
            if isinstance(value, Decimal):
                bucket[key] = format(value, ".6f") if key.startswith("quantity_") else money(value)
    periods = (await session.scalars(select(Period).where(
        Period.organization_id == org_id, Period.month <= end.strftime("%Y-%m")
    ))).all()
    pending = (await session.scalars(select(Inbox.id).where(
        Inbox.organization_id == org_id, Inbox.month <= end.strftime("%Y-%m"),
        Inbox.entry_id.is_(None),
    ))).all()
    final = (any(p.month == end.strftime("%Y-%m") for p in periods)
             and all(p.closed for p in periods) and not pending)
    primary_pending = (await session.scalars(select(SourceControl.id).where(
        SourceControl.organization_id == org_id, SourceControl.month <= end.strftime("%Y-%m"),
        SourceControl.entry_id.is_(None),
    ))).all()
    final = final and not primary_pending
    review_items = []
    # A closed period is not enough to label a report final: unresolved VAT,
    # foreign-trade, depreciation, production, repair or late-cost evidence
    # keeps the report preliminary.  Reuse the accountant's read-only control
    # snapshot only for a complete calendar month so arbitrary date-range
    # reports do not inspect records beyond their requested end date.
    month_first = end.replace(day=1)
    month_last = end.replace(day=monthrange(end.year, end.month)[1])
    if start == month_first and end == month_last:
        from modules.accounting.closing_controls import snapshot as closing_snapshot

        review_items = (await closing_snapshot(session, org_id, end.strftime("%Y-%m")))['review_items']
        final = final and not review_items
    # Unclosed income/expense account balances remain an explicit current result.
    current_result = -balances["income"] - balances["expense"]
    assets, liabilities, equity = balances["asset"], -balances["liability"], -balances["equity"]
    difference = assets - liabilities - equity - current_result
    return {
        "organization_id": org_id, "from": str(start), "to": str(end),
        "status": "closed_periods" if final else "preliminary",
        "review_items": review_items,
        "statutory_certified": False,
        "pending_documents": len(pending) + len(primary_pending), "trial_balance": list(trial.values()),
        "movements": movements,
        "opening_movements": opening_movements,
        "balance": {"assets": money(assets), "liabilities": money(liabilities),
                    "equity": money(equity), "current_result": money(current_result),
                    "difference": money(difference)},
        "pnl": {"income": money(-pnl["income"]), "expenses": money(pnl["expense"]),
                "profit": money(-pnl["income"] - pnl["expense"])},
        "cashflow": {**{k: money(v) for k, v in cash.items()},
                     "closing": money(cash["opening"] + cash["movement"])},
    }
