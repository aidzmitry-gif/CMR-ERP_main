"""Read-only document balances from posted trade settlement lines.

Only the journal is an amount source. A mutable sales invoice, its current
status, and legacy finance payments cannot change a historical balance here.
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from decimal import Decimal

from sqlalchemy import select

from modules.accounting.models import Entry, Line
from modules.accounting.service import AccountingError, lock_organization


def _money(value: Decimal) -> str:
    return format(value, ".2f")


def _dimension(dimensions: dict, name: str) -> str | None:
    value = dimensions.get(name)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _classification(code: str, category: str, document: str | None, complete: bool) -> str:
    if not complete:
        return "unassigned"
    if document.startswith("customer-advance:"):
        return "customer_advance"
    if document.startswith("supplier-advance:"):
        return "supplier_advance"
    root = code.split(".", 1)[0]
    if root == "62" and category == "asset":
        return "receivable"
    if root == "60" and category == "liability":
        return "payable"
    return "unclassified"


def _reconcile_with_trial_balance(output: list[dict], osv: dict) -> dict:
    fields = ("opening", "debit", "credit", "closing")
    accounts = defaultdict(lambda: {field: Decimal("0") for field in fields})
    documents = defaultdict(lambda: {field: Decimal("0") for field in fields})
    osv_movements = {}
    document_ids = []
    for row in osv["trial_balance"]:
        if row["account"].split(".", 1)[0] in {"60", "62"}:
            for field in fields:
                accounts[row["account"]][field] += Decimal(row[field])
    for row in output:
        for field in fields:
            documents[row["account"]][field] += Decimal(row[field + "_byn"])
        document_ids.extend(movement["line_id"] for movement in row["movements"])
    for movement in (*osv["opening_movements"], *osv["movements"]):
        if movement["account"].split(".", 1)[0] in {"60", "62"}:
            osv_movements[movement["line_id"]] = movement
    missing_ids = set(osv_movements) - set(document_ids)
    extra_ids = set(document_ids) - set(osv_movements)
    comparisons = [{
        "account": code,
        "osv_byn": {field: _money(accounts[code][field]) for field in fields},
        "documents_byn": {field: _money(documents[code][field]) for field in fields},
        "matched": accounts[code] == documents[code],
    } for code in sorted(set(accounts) | set(documents))]
    line_counts_match = len(document_ids) == len(osv_movements)
    matched = (all(row["matched"] for row in comparisons)
               and line_counts_match and not missing_ids and not extra_ids)
    return {
        "status": "matched" if matched else "mismatch",
        "basis": "same_posted_journal",
        "osv_line_count": len(osv_movements),
        "document_line_count": len(document_ids),
        "missing_osv_lines": len(missing_ids),
        "extra_document_lines": len(extra_ids),
        "missing_postings": [{"entry_id": osv_movements[line_id]["entry_id"], "line_id": line_id}
                             for line_id in sorted(missing_ids)[:20]],
        "accounts": comparisons,
    }


async def report(session, org_id, start, end):
    from modules.accounting import reports as ledger_reports
    from modules.accounting.closing_commands import authenticated_entries
    from modules.accounting.fx_revaluation import valuation_currencies

    if end < start:
        raise AccountingError("End precedes start")
    # Writers take this organization lock as well. Avoid a mixed-period view.
    await lock_organization(session, org_id)
    technical = await authenticated_entries(session, org_id)
    valuation = await valuation_currencies(session, org_id, end)
    rows = (await session.execute(select(Entry, Line).join(Line, Line.entry_id == Entry.id).where(
        Entry.organization_id == org_id, Entry.posting_date <= end,
    ).order_by(Entry.posting_date, Entry.id, Line.id))).all()
    grouped = {}
    for entry, line in rows:
        if entry.operation in {"period_close", "period_reopen"} and entry.id not in technical:
            raise AccountingError("Technical financial entry has no verified receipt")
        if (line.account_code.split(".", 1)[0] not in {"60", "62"}
                or line.category not in {"asset", "liability"} or line.cash):
            continue
        dimensions = line.dimensions if isinstance(line.dimensions, dict) else {}
        party = _dimension(dimensions, "counterparty")
        contract = _dimension(dimensions, "contract")
        document = _dimension(dimensions, "settlement_document")
        complete = bool(party and contract and document)
        # Never combine anonymous lines into an apparently known document.
        position_currency = valuation.get(line.id, line.currency)
        # Ledger amounts are BYN. A BYN bank settlement can discharge a
        # foreign-currency position of the same document; keep attribution as
        # review evidence, but do not split the document's BYN balance.
        identity = [line.account_code, line.category, party, contract, document]
        if not complete:
            identity.append(line.id)
        key = json.dumps(identity, ensure_ascii=False, separators=(",", ":"))
        item = grouped.setdefault(key, {
            "key": hashlib.sha256(key.encode("utf-8")).hexdigest(),
            "account": line.account_code, "account_title": line.account_title,
            "category": line.category, "currencies": set(),
            "counterparty": party, "contract": contract, "document": document,
            "analytics_complete": complete,
            "classification": _classification(line.account_code, line.category, document, complete),
            "opening": Decimal("0"), "debit": Decimal("0"), "credit": Decimal("0"),
            "bank_receipts": Decimal("0"), "bank_payments": Decimal("0"),
            "offset_debit": Decimal("0"), "offset_credit": Decimal("0"),
            "movements": [],
        })
        item["currencies"].add(position_currency)
        before = entry.posting_date < start or (entry.opening and entry.posting_date <= start)
        signed = line.amount if line.side == "debit" else -line.amount
        if before:
            item["opening"] += signed
        else:
            item[line.side] += line.amount
        kind = "posting"
        if entry.operation == "bank_settlement":
            kind = "bank_receipt" if line.side == "credit" else "bank_payment"
            if not before:
                item["bank_receipts" if line.side == "credit" else "bank_payments"] += line.amount
        elif entry.operation == "settlement_offset":
            kind = "advance_offset"
            if not before:
                item["offset_debit" if line.side == "debit" else "offset_credit"] += line.amount
        item["movements"].append({
            "entry_id": entry.id, "line_id": line.id, "date": str(entry.posting_date),
            "source": entry.source, "source_version": entry.source_version,
            "operation": entry.operation, "correction_of": entry.correction_of,
            "side": line.side, "amount_byn": _money(line.amount),
            "period_bucket": "opening" if before else "movement", "kind": kind,
            "account_title": line.account_title, "dimensions": dimensions,
        })

    totals = defaultdict(lambda: Decimal("0"))
    output = []
    for item in grouped.values():
        item["currencies"] = sorted(item["currencies"])
        closing = item["opening"] + item["debit"] - item["credit"]
        classification = item["classification"]
        if (classification in {"receivable", "supplier_advance"} and closing > 0
                or classification in {"payable", "customer_advance"} and closing < 0):
            totals[classification] += abs(closing)
            balance_kind = classification
        elif closing:
            totals["unclassified"] += abs(closing)
            balance_kind = "unclassified"
        else:
            balance_kind = "settled"
        item["balance_kind"] = balance_kind
        item["closing"] = closing
        for field in ("opening", "debit", "credit", "closing", "bank_receipts",
                      "bank_payments", "offset_debit", "offset_credit"):
            item[field + "_byn"] = _money(item.pop(field))
        output.append(item)
    output.sort(key=lambda item: (item["counterparty"] or "", item["contract"] or "",
                                  item["document"] or "", item["account"], item["key"]))
    osv = await ledger_reports.report(session, org_id, start, end)
    reconciliation = _reconcile_with_trial_balance(output, osv)
    return {
        "organization_id": org_id, "from": str(start), "to": str(end),
        "status": "preliminary", "scope": "posted_accounts_60_62",
        "statutory_certified": False, "due_dates_verified": False,
        "osv_reconciliation": reconciliation,
        "review_items": [
            {"code": "incomplete_analytics", "count": sum(not item["analytics_complete"] for item in output)},
            {"code": "unclassified_balance", "count": sum(item["balance_kind"] == "unclassified" for item in output)},
            {"code": "mixed_currency_document", "count": sum(len(item["currencies"]) > 1 for item in output)},
            {"code": "osv_document_mismatch", "count": int(reconciliation["status"] == "mismatch")},
        ],
        "totals_byn": {name: _money(totals[name]) for name in
                       ("receivable", "payable", "customer_advance", "supplier_advance", "unclassified")},
        "rows": output,
    }
