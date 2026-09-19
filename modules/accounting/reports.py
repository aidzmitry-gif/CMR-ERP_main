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
    from modules.accounting.fx_revaluation import valuation_currencies

    if end < start:
        raise AccountingError("End precedes start")
    # Hold the same lock as all ledger/period writers for one coherent report.
    # A multi-query READ COMMITTED report must not mix old amounts with a new close.
    await lock_organization(session, org_id)
    technical = await authenticated_entries(session, org_id)
    valuation = await valuation_currencies(session, org_id, end)
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
        position_currency = valuation.get(line.id, line.currency)
        key = (line.account_code, json.dumps(line.dimensions, sort_keys=True), position_currency)
        bucket = trial.setdefault(key, {
            "account": line.account_code, "title": line.account_title,
            "dimensions": line.dimensions, "currency": position_currency,
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
                "line_id": line.id, "currency": position_currency,
                **({"ledger_currency": line.currency, "valuation_only": True} if line.id in valuation else {}),
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
    from modules.accounting.bank_import import pending_count

    bank_pending = await pending_count(session, org_id, end)
    final = final and not primary_pending and not bank_pending
    review_items = []
    # Review every complete month in monthly, quarterly and annual reports.
    # Partial ranges must not inspect source records beyond their end date.
    month_last = end.replace(day=monthrange(end.year, end.month)[1])
    if start.day == 1 and end == month_last:
        from modules.accounting.closing_controls import snapshot as closing_snapshot

        month = start
        grouped = {}
        while month <= end:
            controls = await closing_snapshot(session, org_id, month.strftime("%Y-%m"))
            items = list(controls["review_items"])
            if not controls["period"]["closed"]:
                items.append({"code": "reporting_period_open", "count": 1,
                              "message": "Не все месяцы отчёта закрыты."})
            for item in items:
                if item["code"] not in grouped:
                    grouped[item["code"]] = {**item, "count": 0, "months": []}
                grouped[item["code"]]["count"] += item["count"]
                grouped[item["code"]]["months"].append(month.strftime("%Y-%m"))
            if month == end.replace(day=1):
                break
            month = month.replace(year=month.year + 1, month=1) if month.month == 12 else month.replace(month=month.month + 1)
        review_items = list(grouped.values())
        final = final and not review_items
    else:
        final = False
        review_items.append({"code": "partial_period_review", "count": 1,
                             "message": "Диапазон включает неполный месяц; проверки закрытия всего месяца к нему не применены."})
    # Unclosed income/expense account balances remain an explicit current result.
    current_result = -balances["income"] - balances["expense"]
    assets, liabilities, equity = balances["asset"], -balances["liability"], -balances["equity"]
    difference = assets - liabilities - equity - current_result
    return {
        "organization_id": org_id, "from": str(start), "to": str(end),
        "status": "closed_periods" if final else "preliminary",
        "review_items": review_items,
        "statutory_certified": False,
        "pending_documents": len(pending) + len(primary_pending) + bank_pending, "trial_balance": list(trial.values()),
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
