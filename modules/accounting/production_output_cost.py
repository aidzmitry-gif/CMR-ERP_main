"""Read-only production output cost basis.

The warehouse confirms physical acceptance, while accounting owns the monetary
cost.  This module joins those two facts for review, but deliberately does not
invent a finished-goods account or post a transfer.  A final transfer is only
possible after the organisation's policy explicitly supplies the required
target account and dimensions.
"""
from __future__ import annotations

import hashlib
import json
from calendar import monthrange
from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy import select

from modules.accounting.models import Policy
from modules.accounting.production_cost_policy import validate_accounts
from modules.accounting.production_cost_sources import cost_sources
from modules.accounting.schemas import ProductionCostPolicyInput
from modules.accounting.service import AccountingError


def _money(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.01")), ".2f")


def _quantity(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.01")), ".2f")


def _parse_money(value: object, label: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise AccountingError(f"Invalid monetary value in {label}") from exc
    if not result.is_finite() or result.as_tuple().exponent < -2:
        raise AccountingError(f"Invalid monetary value in {label}")
    return result


def _parse_quantity(value: object, label: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise AccountingError(f"Invalid quantity in {label}") from exc
    if not result.is_finite() or result < 0:
        raise AccountingError(f"Invalid quantity in {label}")
    return result


def _basis_digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def _order_balance(source: dict, wip_account: str, order_dimension: str,
                   analytical_order: str) -> tuple[Decimal, list[dict]]:
    """Return the exact WIP balance and its trace for one analytic order."""
    lines = []
    balance = Decimal("0")
    for line in source["snapshot"]["lines"]:
        if line["account"] != wip_account or line["dimensions"].get(order_dimension) != analytical_order:
            continue
        amount = _parse_money(line["amount_byn"], f"line {line['line_id']}")
        balance += amount if line["side"] == "debit" else -amount
        lines.append({
            "entry_id": line["entry_id"],
            "line_id": line["line_id"],
            "source": line["source"],
            "posting_date": line["posting_date"],
            "side": line["side"],
            "amount_byn": _money(amount),
            "dimensions": line["dimensions"],
            "opening": line["opening"],
        })
    return balance, lines


async def preview_output_cost_basis(session, org_id: int, month: str, policy_id: int,
                                    order_id: int, analytical_order: str, warehouse: str,
                                    production, warehouse_gateway):
    """Build a reviewable WIP-to-output basis without creating a ledger entry.

    The result remains provisional whenever the accepted quantity is incomplete,
    the WIP balance is missing/negative, or policy has no explicit disposition
    account.  All such states are returned as data for the accountant instead of
    being replaced by a zero or a guessed account.
    """
    if not isinstance(month, str):
        raise AccountingError("Month is required")
    first = date.fromisoformat(month + "-01")
    last = first.replace(day=monthrange(first.year, first.month)[1])
    if not isinstance(order_id, int) or order_id <= 0:
        raise AccountingError("A positive production order is required")
    if not analytical_order or not analytical_order.strip() or len(analytical_order) > 200:
        raise AccountingError("A reviewed production order analytic is required")
    if not warehouse or not warehouse.strip() or len(warehouse) > 128:
        raise AccountingError("A warehouse is required for output reconciliation")
    if production is None or warehouse_gateway is None:
        raise AccountingError("Production and warehouse reconciliation services are unavailable")

    policy = await session.scalar(select(Policy).where(
        Policy.organization_id == org_id, Policy.effective_from <= last,
    ).order_by(Policy.effective_from.desc()))
    if policy is None or policy.id != policy_id or policy.effective_from > first:
        raise AccountingError("Select one applicable production policy for the whole reviewed month")
    if policy.production_costing is None:
        raise AccountingError("Production cost configuration is required")
    settings = ProductionCostPolicyInput.model_validate(policy.production_costing)
    await validate_accounts(session, org_id, last, settings)

    # Read the ledger under the organisation lock first.  The subsequent
    # production-order lock then follows the same order as other accounting
    # operations and avoids an org/order versus order/org deadlock.
    source = await cost_sources(session, org_id, month, policy_id)
    wip_balance, source_lines = _order_balance(source, settings.wip_account,
                                               settings.order_dimension, analytical_order.strip())
    if wip_balance < 0:
        raise AccountingError("WIP balance for the production order is negative; reconcile the ledger first")

    # Both calls verify the organisation-owned production order.  The gateway
    # is queried even when no ledger lines exist so a foreign or stale order
    # cannot be exposed as an accounting balance.
    orders = await production.cost_orders(session, org_id, [order_id])
    if len(orders) != 1:
        raise AccountingError("Production order verification returned an unexpected result")
    output = await production.output_reconciliation(session, org_id, order_id, warehouse_gateway)

    planned = _parse_quantity(output["planned_quantity"], "planned output")
    confirmed = _parse_quantity(output["confirmed_quantity"], "confirmed output")
    accepted = _parse_quantity(output["accepted_quantity"], "accepted output")
    rejected = _parse_quantity(output["rejected_quantity"], "rejected output")
    pending = _parse_quantity(output["pending_quantity"], "pending output")
    if planned <= 0:
        raise AccountingError("Production order quantity must be positive")
    documents = output.get("documents", [])
    try:
        document_dates = [date.fromisoformat(item["operation_date"]) for item in documents]
    except (KeyError, TypeError, ValueError) as exc:
        raise AccountingError("Production output documents have no valid operation date") from exc
    aligned = bool(document_dates) and all(item.strftime("%Y-%m") == month for item in document_dates)
    complete = (confirmed == planned and accepted == planned and rejected == 0 and pending == 0 and aligned)

    target_account = None
    # This key is intentionally read only from a versioned policy snapshot. It
    # is not defaulted to account 43 or any other statutory number.
    raw_target = policy.production_costing.get("finished_goods_account")
    if isinstance(raw_target, str) and raw_target.strip():
        target_account = raw_target.strip()

    if not source_lines:
        status = "awaiting_wip_cost"
        explanation = "По аналитике наряда нет проведённой стоимости НЗП. Сумма выпуска не определяется."
    elif confirmed == planned and accepted == planned and rejected == 0 and pending == 0 and not aligned:
        status = "awaiting_output_period_alignment"
        explanation = "Даты подтверждённых выпусков не совпадают с выбранным периодом; стоимость нельзя переносить в него автоматически."
    elif not complete:
        status = "awaiting_full_accepted_output"
        explanation = "Выпуск не принят полностью на склад; перенос стоимости в готовую продукцию не подтверждается."
    elif target_account is None:
        status = "awaiting_finished_goods_policy"
        explanation = "В учётной политике нет явного счёта готовой продукции; нормативный счёт автоматически не выбирается."
    else:
        status = "ready_for_transfer_review"
        explanation = "Физический выпуск принят полностью и стоимость НЗП найдена; проводка всё ещё требует отдельного подтверждения."

    source_digest = source.get("digest")
    if not isinstance(source_digest, str) or len(source_digest) != 64:
        source_digest = _basis_digest(source.get("snapshot", {}))
    basis_digest = _basis_digest({
        "organization_id": org_id, "month": month, "policy_id": policy.id,
        "order": orders[0], "analytical_order": analytical_order.strip(),
        "warehouse": warehouse.strip(), "source_digest": source_digest, "output": output,
    })

    result = {
        "organization_id": org_id,
        "month": month,
        "policy_id": policy.id,
        "policy_reference": policy.reference,
        "order": orders[0],
        "analytical_order": analytical_order.strip(),
        "warehouse": warehouse.strip(),
        "output": {
            "planned_quantity": _quantity(planned),
            "confirmed_quantity": _quantity(confirmed),
            "accepted_quantity": _quantity(accepted),
            "rejected_quantity": _quantity(rejected),
            "pending_quantity": _quantity(pending),
            "sku_code": output.get("sku_code"),
            "unit": output.get("unit"),
            "lot": output.get("lot"),
            "documents": documents,
        },
        "wip": {
            "account": settings.wip_account,
            "balance_byn": _money(wip_balance),
            "source_lines": source_lines,
        },
        "target": {"finished_goods_account": target_account},
        "status": status,
        "explanation": explanation,
        "posting_available": False,
        "final_cost_certified": False,
        "scope": "production_output_cost_basis",
        "basis_digest": basis_digest,
    }
    if complete and wip_balance > 0:
        result["wip"]["unit_cost_byn"] = format(wip_balance / planned, ".6f")
        result["candidate_transfer_byn"] = _money(wip_balance)
    else:
        result["candidate_transfer_byn"] = None
    return result
