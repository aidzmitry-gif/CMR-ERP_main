"""Load receipt-authenticated explicit inventory allocations for internal replay."""

import hashlib
import json
from dataclasses import dataclass
from datetime import date

from pydantic import ValidationError
from sqlalchemy import or_, select

from modules.accounting.closing_commands import actual_posting
from modules.accounting.inventory_allocation_receipts import validate_inventory_disposition_binding
from modules.accounting.models import (
    Entry,
    InventoryIssueReceipt,
    InventorySaleReceipt,
    Line,
    Policy,
)
from modules.accounting.sales import SaleDocument
from modules.accounting.schemas import InventoryIssueDocument, PostingInput
from modules.accounting.service import AccountingError, lock_organization
from modules.accounting.zero_value_disposals import InventoryDispositionAllocation


def _snapshot_digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


@dataclass(frozen=True)
class AuthenticatedInventoryDisposition:
    """Immutable-by-checksum replay event for one posted issue or sale allocation."""

    entry_id: int
    registration_token: int
    organization_id: int
    posting_date: date
    source: str
    source_version: int
    allocation: InventoryDispositionAllocation
    replaced_credit_line_ids: tuple[int, ...]
    snapshot_digest: str
    selection_lot: str = ""

    def verify_snapshot(self) -> None:
        if (type(self.entry_id) is not int or self.entry_id <= 0
                or type(self.registration_token) is not int or self.registration_token != self.entry_id
                or type(self.organization_id) is not int or self.organization_id <= 0
                or len(self.replaced_credit_line_ids) != len(set(self.replaced_credit_line_ids))
                or any(type(line_id) is not int or line_id <= 0 for line_id in self.replaced_credit_line_ids)):
            raise AccountingError("Inventory allocation replay identity is invalid")
        snapshot = _snapshot(self.entry_id, self.registration_token, self.organization_id, self.posting_date,
                             self.source, self.source_version, self.allocation, self.replaced_credit_line_ids, self.selection_lot)
        if self.snapshot_digest != _snapshot_digest(snapshot):
            raise AccountingError("Inventory allocation replay snapshot changed")


def _snapshot(entry_id, registration_token, organization_id, posting_date, source, source_version, allocation, line_ids, selection_lot=""):
    return {"entry_id": entry_id, "registration_token": registration_token, "organization_id": organization_id,
            "posting_date": posting_date.isoformat(), "source": source, "source_version": source_version,
            "allocation": allocation.model_dump(mode="json"), "replaced_credit_line_ids": list(line_ids),
            "selection_lot": selection_lot}


def _receipt_rows(session, organization_id):
    issue = select(Entry, InventoryIssueReceipt).join(InventoryIssueReceipt, InventoryIssueReceipt.entry_id == Entry.id).where(
        Entry.organization_id == organization_id)
    sale = select(Entry, InventorySaleReceipt).join(InventorySaleReceipt, InventorySaleReceipt.entry_id == Entry.id).where(
        Entry.organization_id == organization_id)
    return issue, sale


def _replaced_credit_line_ids(lines, account, allocation):
    credits = [line for line in lines if line.side == "credit" and line.account_code == account]
    positive = [layer for layer in allocation.layers if layer.amount_byn > 0]
    if len(credits) != len(positive):
        raise AccountingError("Inventory allocation does not replace exact saved credits")
    for line, layer in zip(credits, positive, strict=True):
        if (line.quantity != layer.quantity or line.amount != layer.amount_byn
                or line.dimensions != layer.inventory_dimensions or line.currency != "BYN"
                or line.category != "asset" or line.cash):
            raise AccountingError("Inventory allocation credit replacement differs from saved posting")
    return tuple(line.id for line in credits)


async def load_authenticated_inventory_dispositions(session, organization_id: int, *, before_entry_id: int | None = None,
                                                    procurement=None, inventory_account: str | None = None):
    """Return only strict-marker receipt allocations, authenticated against live DB rows.

    This is internal replay groundwork. It neither enables a write path nor
    accepts a legacy receipt as a new allocation event.
    """
    if type(organization_id) is not int or organization_id <= 0:
        raise ValueError("Inventory allocation organization must be a positive integer")
    if before_entry_id is not None and (type(before_entry_id) is not int or before_entry_id <= 0):
        raise ValueError("Inventory allocation replay cutoff must be a positive entry id")
    await lock_organization(session, organization_id)
    issue_query, sale_query = _receipt_rows(session, organization_id)
    if inventory_account is not None:
        # Include either representation, so a forged command cannot conceal an
        # actual inventory credit on the requested account (or vice versa).
        actual = Entry.id.in_(select(Line.entry_id).where(Line.account_code == inventory_account))
        issue_query = issue_query.where(or_(InventoryIssueReceipt.command["account"].as_string() == inventory_account, actual))
        sale_query = sale_query.where(or_(InventorySaleReceipt.command["account"].as_string() == inventory_account, actual))
    rows = list((await session.execute(issue_query)).all()) + list((await session.execute(sale_query)).all())
    result = []
    seen_entries, seen_lines = set(), set()
    for entry, receipt in sorted(rows, key=lambda row: row[0].id):
        if before_entry_id is not None and entry.id >= before_entry_id:
            continue
        if not isinstance(receipt.cost, dict):
            raise AccountingError("Inventory receipt cost snapshot is invalid")
        if "source_allocation_version" not in receipt.cost:
            continue
        marker = receipt.cost["source_allocation_version"]
        if type(marker) is not int or marker != 1:
            raise AccountingError("Inventory receipt has an unsupported explicit allocation marker")
        if entry.id in seen_entries:
            raise AccountingError("Inventory allocation has duplicate receipt entries")
        try:
            document_type = SaleDocument if entry.operation == "inventory_sale" else InventoryIssueDocument
            document = document_type.model_validate(receipt.command)
            saved_posting = PostingInput.model_validate(receipt.posting)
        except ValidationError as error:
            raise AccountingError("Inventory allocation receipt snapshot is invalid") from error
        if (entry.operation not in {"inventory_issue", "inventory_sale"}
                or (await actual_posting(session, entry)).model_dump() != saved_posting.model_dump()):
            raise AccountingError("Inventory allocation receipt posting changed")
        allocation_payload = {
            "allocation_version": marker, "valuation_method": receipt.cost.get("method"),
            "quantity": receipt.cost.get("issue_quantity"), "amount_byn": receipt.cost.get("issue_cost_byn"),
            "layers": [{"source_entry_id": layer.get("source_entry_id"), "source_line_id": layer.get("source_line_id"),
                        "inventory_account": document.account, "inventory_dimensions": layer.get("dimensions"),
                        "quantity": layer.get("quantity"), "amount_byn": layer.get("amount_byn")}
                       for layer in receipt.cost.get("inventory_layers", [])]}
        validate_inventory_disposition_binding(entry, receipt, document, allocation_payload, organization_id=organization_id)
        allocation = InventoryDispositionAllocation.model_validate(allocation_payload)
        policy = await session.scalar(select(Policy).where(Policy.organization_id == organization_id,
            Policy.effective_from <= entry.posting_date).order_by(Policy.effective_from.desc()).limit(1))
        if (policy is None or policy.id != entry.policy_id or policy.inventory_method != allocation.valuation_method):
            raise AccountingError("Inventory allocation policy is not effective for its entry")
        for layer in allocation.layers:
            origin = (await session.execute(select(Entry, Line).join(Line, Line.entry_id == Entry.id).where(
                Entry.id == layer.source_entry_id, Line.id == layer.source_line_id))).one_or_none()
            if origin is None:
                raise AccountingError("Inventory allocation source line is missing")
            source_entry, source_line = origin
            if (source_entry.organization_id != organization_id or source_line.side != "debit" or source_line.quantity is None
                    or source_line.quantity <= 0 or source_line.account_code != layer.inventory_account
                    or source_line.dimensions != layer.inventory_dimensions or source_line.currency != "BYN"
                    or source_line.category != "asset" or source_line.cash or source_entry.id >= entry.id
                    or source_entry.posting_date > entry.posting_date):
                raise AccountingError("Inventory allocation source line is not a prior owned inventory debit")
        lines = (await session.scalars(select(Line).where(Line.entry_id == entry.id).order_by(Line.id))).all()
        replaced = _replaced_credit_line_ids(lines, document.account, allocation)
        if set(replaced) & seen_lines:
            raise AccountingError("Inventory allocation replaces a credit more than once")
        seen_entries.add(entry.id)
        seen_lines.update(replaced)
        line_ids = tuple(replaced)
        snapshot = _snapshot(entry.id, entry.id, organization_id, entry.posting_date, entry.source,
                             entry.source_version, allocation, line_ids, document.lot)
        event = AuthenticatedInventoryDisposition(entry.id, entry.id, organization_id, entry.posting_date,
                                                  entry.source, entry.source_version, allocation, line_ids,
                                                  _snapshot_digest(snapshot), document.lot)
        event.verify_snapshot()
        await _verify_historical_cost(session, entry, receipt, document, policy, tuple(result), procurement)
        result.append(event)
    return tuple(result)


async def _verify_historical_cost(session, entry, receipt, document, policy, prior_events, procurement):
    """Rebuild the saved preview from only evidence registered before this entry."""
    from modules.accounting.inventory_cost import issue_result
    from modules.accounting.late_cost_receipts import verified_value_lines
    from modules.accounting.production_output_inventory import (
        is_finished_goods_account,
        verified_output_lines,
    )
    from modules.accounting.schemas import InventoryIssuePreviewInput
    from modules.accounting.zero_value_disposals import available_authenticated_zero_value_disposals

    rows = (await session.execute(select(Entry, Line).join(Line, Line.entry_id == Entry.id).where(
        Entry.organization_id == entry.organization_id, Entry.id < entry.id,
        Line.account_code == document.account,
    ).order_by(Entry.posting_date, Entry.id, Line.id))).all()
    values = await verified_value_lines(session, entry.organization_id, rows, procurement)
    finished = is_finished_goods_account(policy, document.account)
    outputs = await verified_output_lines(session, entry.organization_id, policy, document.account,
        entry.posting_date, {"warehouse": document.warehouse, "sku": document.sku, "lot": document.lot},
        before_entry_id=entry.id) if finished else frozenset()
    zeros = await available_authenticated_zero_value_disposals(session, entry.organization_id,
                                                               before_registration_token=entry.id)
    request = InventoryIssuePreviewInput(**document.model_dump(include=set(InventoryIssuePreviewInput.model_fields)))
    calculated = issue_result(policy, rows, entry.organization_id, request, verified_value_lines=values,
        verified_output_lines=outputs, finished_goods=finished, zero_value_disposals=zeros,
        authenticated_dispositions=prior_events, before_registration_token=entry.id, include_source_identity=True)
    calculated["source_allocation_version"] = 1
    if json.loads(json.dumps(calculated, default=str)) != receipt.cost:
        raise AccountingError("Inventory allocation saved cost differs from its historical calculation")
