"""Gross profit at shipment posting, from verified immutable whole-act receipts.

No latest stock price, invoice total or estimate can replace the recorded COGS.
This deliberately reports the initial recognition, not a restated final margin.
"""
import hashlib
import json
from datetime import date
from decimal import Decimal, localcontext

from sqlalchemy import select

from modules.accounting import service, shipment_commands
from modules.accounting.assembly_estimate import money
from modules.accounting.models import Entry, ShipmentAccountingReceipt


def summarize(saved):
    snapshot = saved.snapshot
    act = snapshot["act"]["snapshot"]
    act_digest = hashlib.sha256(json.dumps(act, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    if act["organization_id"] != saved.organization_id or act_digest != saved.act_digest:
        raise service.AccountingError("Shipment profit organization mismatch")
    with localcontext() as context:
        context.prec = 80
        net = sum((Decimal(row["net_byn"]) for row in snapshot["commercial"]), Decimal(0))
        vat = sum((Decimal(row["vat_byn"]) for row in snapshot["commercial"]), Decimal(0))
        cost = sum((Decimal(row["cost_byn"]) for row in snapshot["mapping"]), Decimal(0))
        bucket_cost = sum((Decimal(row["issue_cost_byn"]) for row in snapshot["costs"]), Decimal(0))
        if not all(value.is_finite() for value in (net, vat, cost, bucket_cost)) or net <= 0 or cost < 0 or cost != bucket_cost:
            raise service.AccountingError("Shipment profit cost evidence is inconsistent")
        return {
            "receipt_id": saved.id, "entry_id": saved.anchor_entry_id, "source": saved.source,
            "document_id": act["document_id"], "operation_date": act["operation_date"],
            "posting_date": saved.command["posting_date"], "status": "at_posting",
            "revenue_net_byn": money(net), "vat_byn": money(vat), "cogs_byn": money(cost),
            "gross_profit_byn": money(net - cost), "margin_percent": money((net - cost) / net * 100),
            "basis_digest": saved.basis_digest,
            "items": [{"sku": row["sku_code"], "quantity": row["qty"]} for row in act["lines"]],
        }


async def report(session, org_id: int, start: date, end: date, *, offset: int = 0, limit: int = 100):
    if start > end or (end - start).days > 366:
        raise service.AccountingError("Выберите период от 1 до 367 дней")
    # Recognition date is the date of the immutable physical act, not the invoice.
    receipts = (await session.scalars(select(ShipmentAccountingReceipt).join(
        Entry, Entry.id == ShipmentAccountingReceipt.anchor_entry_id,
    ).where(
        ShipmentAccountingReceipt.organization_id == org_id, Entry.organization_id == org_id,
        Entry.operation_date >= start, Entry.operation_date <= end,
    ).order_by(Entry.operation_date.desc(), ShipmentAccountingReceipt.id.desc())
        .offset(offset).limit(limit + 1))).all()
    rows = []
    for saved in receipts[:limit]:
        try:
            await shipment_commands.verify_saved(session, saved)
            row = summarize(saved)
            if not start <= date.fromisoformat(row["operation_date"]) <= end:
                raise service.AccountingError("Shipment profit operation date mismatch")
            rows.append(row)
        except (ValueError, KeyError, TypeError, ArithmeticError) as exc:
            raise service.AccountingError("Не удалось проверить сохранённые данные отгрузки") from exc
    # A page subtotal is explicitly NOT a period total. Margin is weighted by revenue.
    with localcontext() as context:
        context.prec = 80
        net = sum((Decimal(row["revenue_net_byn"]) for row in rows), Decimal(0))
        cost = sum((Decimal(row["cogs_byn"]) for row in rows), Decimal(0))
        subtotal = {"revenue_net_byn": money(net), "cogs_byn": money(cost),
                    "gross_profit_byn": money(net - cost),
                    "margin_percent": money((net - cost) / net * 100) if net else None}
    return {"organization_id": org_id, "start": start.isoformat(), "end": end.isoformat(),
            "currency": "BYN", "basis": "at_posting", "rows": rows, "page_subtotal": subtotal,
            "offset": offset, "has_more": len(receipts) > limit,
            "includes_unposted_shipments": False, "includes_later_adjustments": False,
            "includes_returns": False}
