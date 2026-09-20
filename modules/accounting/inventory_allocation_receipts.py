"""Pure binding checks for explicit inventory allocations and saved receipts."""

import re
from decimal import Decimal

from pydantic import ValidationError

from modules.accounting.sales import SaleDocument
from modules.accounting.schemas import InventoryIssueDocument, PostingInput
from modules.accounting.service import AccountingError, digest
from modules.accounting.zero_value_disposals import InventoryDispositionAllocation


def validate_inventory_disposition_binding(entry, receipt, document, allocation, *, organization_id: int) -> None:
    """Bind an explicit FIFO/weighted allocation to one saved issue or sale receipt.

    ``entry`` and ``receipt`` are already loaded persistence objects; this pure
    check deliberately does not authorize their accounts, source lineage, or
    database visibility. A loader must perform those checks before calling it.
    """
    if not isinstance(document, InventoryIssueDocument):
        raise AccountingError("Allocation binding requires an inventory issue or sale document")
    if entry is None or receipt is None or type(getattr(entry, "id", None)) is not int or entry.id <= 0:
        raise AccountingError("Explicit allocation requires a posted ledger entry")
    if getattr(receipt, "entry_id", None) != entry.id:
        raise AccountingError("Allocation receipt is not bound to the ledger entry")
    if type(organization_id) is not int or organization_id <= 0:
        raise AccountingError("Allocation organization must be a positive integer")
    if entry.organization_id != organization_id or receipt.organization_id != organization_id:
        raise AccountingError("Allocation receipt organization differs from entry")
    if not isinstance(receipt.actor, str) or not receipt.actor.strip() or receipt.actor != receipt.actor.strip() or entry.actor != receipt.actor or entry.digest != receipt.digest:
        raise AccountingError("Allocation receipt actor or digest differs from entry")
    if receipt.command != document.model_dump(mode="json"):
        raise AccountingError("Allocation receipt command differs from document")

    expected_operation = "inventory_sale" if isinstance(document, SaleDocument) else "inventory_issue"
    for field in ("source", "source_version", "document_date", "operation_date", "posting_date", "policy_id"):
        if getattr(entry, field) != getattr(document, field):
            raise AccountingError("Allocation entry identity differs from document")
    if entry.operation != expected_operation:
        raise AccountingError("Allocation entry operation differs from document")

    try:
        posting = PostingInput.model_validate(receipt.posting)
        if isinstance(allocation, dict) and type(allocation.get("allocation_version")) is not int:
            raise AccountingError("Allocation version must be a strict integer")
        selected = InventoryDispositionAllocation.model_validate(allocation)
    except ValidationError as error:
        raise AccountingError("Allocation receipt packet is invalid") from error
    if digest(posting) != receipt.digest:
        raise AccountingError("Allocation receipt posting digest differs")
    if any(getattr(posting, field) != getattr(document, field)
           for field in ("source", "source_version", "document_date", "operation_date", "posting_date", "policy_id")):
        raise AccountingError("Allocation posting identity differs from document")
    if posting.operation != expected_operation:
        raise AccountingError("Allocation posting operation differs from document")
    if posting.rule_version != entry.rule_version or posting.explanation != document.explanation or entry.explanation != document.explanation:
        raise AccountingError("Allocation posting rule or explanation differs from entry")
    if posting.opening or posting.correction_of is not None or entry.opening or entry.correction_of is not None:
        raise AccountingError("Inventory disposal cannot be an opening or correction entry")

    cost = receipt.cost
    if not isinstance(cost, dict) or type(cost.get("source_allocation_version")) is not int or cost.get("source_allocation_version") != 1:
        raise AccountingError("Legacy receipt has no explicit allocation")
    document_json = document.model_dump(mode="json")
    if (cost.get("organization_id") != organization_id
            or any(cost.get(field) != document_json[field] for field in ("policy_id", "posting_date", "account"))):
        raise AccountingError("Saved cost identity differs from document")
    if not isinstance(cost.get("basis_digest"), str) or not re.fullmatch(r"[0-9a-f]{64}", cost["basis_digest"]):
        raise AccountingError("Saved cost basis digest is invalid")
    try:
        saved = InventoryDispositionAllocation.model_validate({
            "allocation_version": cost["source_allocation_version"],
            "valuation_method": cost["method"],
            "quantity": cost["issue_quantity"],
            "amount_byn": cost["issue_cost_byn"],
            "layers": [{
                "source_entry_id": layer["source_entry_id"],
                "source_line_id": layer["source_line_id"],
                "inventory_account": document.account,
                "inventory_dimensions": layer["dimensions"],
                "quantity": layer["quantity"],
                "amount_byn": layer["amount_byn"],
            } for layer in cost["inventory_layers"]],
        })
    except (KeyError, TypeError, ValidationError) as error:
        raise AccountingError("Saved cost has no valid explicit allocation") from error
    if selected != saved:
        raise AccountingError("Allocation differs from saved cost selection")
    if selected.quantity != document.quantity:
        raise AccountingError("Allocation quantity differs from document")
    for layer in selected.layers:
        dimensions = layer.inventory_dimensions
        if (layer.inventory_account != document.account
                or dimensions.get("warehouse") != document.warehouse
                or dimensions.get("sku") != document.sku
                or document.lot and dimensions.get("lot") != document.lot):
            raise AccountingError("Allocation inventory identity differs from document")

    inventory_lines = [line for line in posting.lines if line.account == document.account]
    if any(line.currency != "BYN" or any(getattr(line, field) is not None for field in (
        "original_amount", "rate", "rate_scale", "rate_date", "rate_source", "cash_activity"
    )) for line in inventory_lines):
        raise AccountingError("Inventory allocation requires BYN credits without currency or cash metadata")
    if any(line.side != "credit" or line.quantity is None for line in inventory_lines):
        raise AccountingError("Saved posting has an invalid inventory movement")
    if any(line.amount <= Decimal(0) for line in posting.lines):
        raise AccountingError("Saved monetary posting contains a nonpositive line")
    positive_layers = [layer for layer in selected.layers if layer.amount_byn > 0]
    actual = [(line.quantity, line.amount, line.dimensions) for line in inventory_lines]
    expected = [(layer.quantity, layer.amount_byn, layer.inventory_dimensions) for layer in positive_layers]
    if actual != expected:
        raise AccountingError("Allocation positive credits differ from saved posting")
