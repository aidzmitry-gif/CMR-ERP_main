"""Authenticated quantity/value trace for one immutable output layer."""
from datetime import date

from sqlalchemy import select

from modules.accounting import inventory_issues, sales
from modules.accounting.closing_commands import actual_posting
from modules.accounting.models import (
    Entry,
    InventoryIssueReceipt,
    InventorySaleReceipt,
    Line,
    ProductionOutputTransferReceipt,
)
from modules.accounting.schemas import PostingInput
from modules.accounting.service import AccountingError, digest


async def trace_output_layer(session, organization_id: int, receipt: ProductionOutputTransferReceipt,
                             through: date, *, before_entry_id: int | None = None):
    """Return only receipt-authenticated movements of the selected FG debit."""
    entry = await session.get(Entry, receipt.entry_id)
    if (receipt.organization_id != organization_id or entry is None
        or entry.organization_id != organization_id or entry.operation != "production_output_transfer"
        or entry.digest != receipt.digest or not isinstance(receipt.posting, dict)):
        raise AccountingError("Output receipt does not match its ledger entry")
    if entry.posting_date > through or (before_entry_id is not None and entry.id >= before_entry_id):
        raise AccountingError("Output receipt is outside the requested history")
    expected = PostingInput.model_validate(receipt.posting)
    if digest(expected) != receipt.digest or (await actual_posting(session, entry)).model_dump() != expected.model_dump():
        raise AccountingError("Output receipt posting package changed")
    lines = (await session.scalars(select(Line).where(Line.entry_id == entry.id).order_by(Line.id))).all()
    debit = [line for line in lines if line.side == "debit"]
    if len(debit) != 1 or debit[0].quantity is None:
        raise AccountingError("Output receipt has ambiguous finished-goods layer")
    origin = debit[0]
    target = dict(origin.dimensions or {})
    if any(not target.get(key) for key in ("warehouse", "sku", "lot")):
        raise AccountingError("Output receipt lacks finished-goods lot identity")
    query = select(Entry, Line).join(Line, Line.entry_id == Entry.id).where(
        Entry.organization_id == organization_id, Line.account_code == origin.account_code,
        Entry.posting_date <= through,
    )
    if before_entry_id is not None:
        query = query.where(Entry.id < before_entry_id)
    rows = (await session.execute(query.order_by(Entry.posting_date, Entry.id, Line.id))).all()
    quantity, value = origin.quantity, origin.amount
    disposals = []
    for movement, line in rows:
        if movement.id == entry.id or (line.dimensions or {}) != target:
            continue
        if line.quantity is None or line.currency != "BYN" or line.category != "asset" or line.cash:
            raise AccountingError("Output layer contains unsupported value-only or non-inventory movement")
        if line.side != "credit" or movement.operation not in {"inventory_issue", "inventory_sale"}:
            raise AccountingError("Output layer has an unverified non-disposal movement")
        saved = await session.get(InventorySaleReceipt if movement.operation == "inventory_sale" else InventoryIssueReceipt,
                                  movement.id)
        if saved is None or saved.organization_id != organization_id or not isinstance(saved.command, dict):
            raise AccountingError("Output disposal has no matching immutable receipt")
        allow_material = movement.operation == "inventory_issue" and saved.command.get("source", "").startswith("production:material:")
        posting = await (sales.verify_receipt(session, organization_id, movement.id)
                         if movement.operation == "inventory_sale"
                         else inventory_issues.verify_receipt(session, organization_id, movement.id,
                                                               allow_production_material=allow_material))
        actual = await actual_posting(session, movement)
        if actual.model_dump() != posting.model_dump():
            raise AccountingError("Output disposal receipt package changed")
        movement_lines = (await session.scalars(select(Line).where(Line.entry_id == movement.id).order_by(Line.id))).all()
        destination = next((item for item in movement_lines if item.side == "debit"
                            and item.account_code == saved.command.get("expense_account")
                            and item.dimensions == saved.command.get("expense_dimensions", {})), None)
        credits = [item for item in movement_lines if item.side == "credit" and item.account_code == origin.account_code]
        if (destination is None or destination.quantity is not None
            or destination.amount != sum((item.amount for item in credits), 0)):
            raise AccountingError("Output disposal destination does not cover its saved inventory credits")
        quantity -= line.quantity
        value -= line.amount
        if quantity < 0 or value < 0:
            raise AccountingError("Output layer quantity/value became negative")
        disposals.append({"entry_id": movement.id, "line_id": line.id, "receipt_entry_id": movement.id,
                          "quantity": format(line.quantity, ".6f"), "applied_cost_byn": format(line.amount, ".2f"),
                          "destination_account": destination.account_code,
                          "destination_dimensions": destination.dimensions})
    return {"output_entry_id": entry.id, "output_line_id": origin.id, "account": origin.account_code,
            "dimensions": target, "received_quantity": format(origin.quantity, ".6f"),
            "received_value_byn": format(origin.amount, ".2f"), "remaining_quantity": format(quantity, ".6f"),
            "remaining_value_byn": format(value, ".2f"), "disposals": disposals}
