"""Trace specific-lot quantities from caller-authenticated posting packages.

The caller must supply the complete book history and authenticate each package;
this helper does not certify a database, choose policy or authorize posting.
"""
from datetime import date
from fractions import Fraction

from modules.accounting.schemas import PostingInput
from modules.accounting.service import AccountingError


def trace_specific_lot(entries: list[tuple[int, PostingInput]], acquisition_id: int,
                       acquisition_line: int, on: date, *, verified_cost_entries=frozenset(),
                       verified_material_entries=frozenset()):
    if len({entry_id for entry_id, _ in entries}) != len(entries):
        raise AccountingError("Duplicate ledger entry identity")
    original = next((posting for entry_id, posting in entries if entry_id == acquisition_id), None)
    if original is None or not 1 <= acquisition_line <= len(original.lines):
        raise AccountingError("Exact acquisition entry and line are required")
    source = original.lines[acquisition_line - 1]
    target = {key: source.dimensions.get(key) for key in ("warehouse", "sku", "lot")}
    if (original.operation != "inventory_purchase" or source.side != "debit"
        or source.account.split(".")[0] not in {"10", "41"} or source.quantity is None
        or source.quantity <= 0 or source.currency != "BYN" or not all(target.values())):
        raise AccountingError("Acquisition must identify owned BYN inventory with lot analytics")
    quantity = Fraction(0)
    value = Fraction(0)
    disposed = Fraction(0)
    production = Fraction(0)
    evidence = []
    material_evidence = []
    traced_material_entries = set()
    if any(type(identity) is not int or identity <= 0 for identity in verified_material_entries):
        raise AccountingError("Verified material identities must be positive integers")
    if not verified_material_entries <= {entry_id for entry_id, _ in entries}:
        raise AccountingError("Verified material history is incomplete")
    for entry_id, posting in sorted(entries, key=lambda item: (item[1].posting_date, item[0])):
        for index, line in enumerate(posting.lines, 1):
            if line.account != source.account:
                continue
            if any(not line.dimensions.get(key) for key in target):
                raise AccountingError("Inventory movement lacks required lot analytics")
            if any(line.dimensions[key] != value for key, value in target.items()):
                continue
            if posting.posting_date > on:
                raise AccountingError("Later lot movements require chronological cost recalculation")
            if line.dimensions != source.dimensions or line.currency != "BYN":
                raise AccountingError("Mixed analytics or value-only movements require explicit cost layers")
            if line.quantity is None:
                if (entry_id not in verified_cost_entries or posting.operation != "inventory_late_cost"
                    or line.side != "debit" or line.amount <= 0 or quantity <= 0):
                    raise AccountingError("Value-only movement requires a verified late-cost receipt and remaining stock")
                value += Fraction(line.amount)
                continue
            if line.side == "debit":
                if (entry_id, index) != (acquisition_id, acquisition_line):
                    raise AccountingError("Multiple acquisitions or returns require explicit cost layers")
                quantity += Fraction(line.quantity)
                value += Fraction(line.amount)
            else:
                if posting.operation not in {"inventory_issue", "inventory_sale"} or index < 2:
                    raise AccountingError("Unsupported inventory disposition requires its source workflow")
                destination = posting.lines[index - 2]
                material = entry_id in verified_material_entries
                if material and (posting.operation != "inventory_issue"
                    or not posting.source.startswith("production:material:")
                    or destination.account.split(".")[0] != "20"):
                    raise AccountingError("Verified material must identify its production WIP destination")
                if (destination.side != "debit" or destination.quantity is not None
                    or destination.currency != "BYN" or destination.amount != line.amount
                    or (not material and destination.account.split(".")[0] not in {"90", "91", "44"})):
                    raise AccountingError("Disposition must have an explicit matching expense destination")
                quantity -= Fraction(line.quantity)
                value -= Fraction(line.amount)
                if material:
                    traced_material_entries.add(entry_id)
                    production += Fraction(line.quantity)
                else:
                    disposed += Fraction(line.quantity)
                (material_evidence if material else evidence).append({"entry_id": entry_id, "inventory_line": index, "quantity": str(line.quantity),
                                 "expense_account": destination.account, "expense_dimensions": destination.dimensions,
                                 "source": posting.source, "source_version": posting.source_version})
            if quantity < 0:
                raise AccountingError("Lot was disposed before acquisition or beyond its quantity")
            if value < 0 or (quantity == 0 and value != 0):
                raise AccountingError("Lot quantity/value history is inconsistent")
    if traced_material_entries != set(verified_material_entries):
        raise AccountingError("Verified material entries do not belong to this source lot")
    if quantity + disposed + production != Fraction(source.quantity):
        raise AccountingError("Lot movement history does not cover the acquisition")
    def exact_quantity(value):
        units = value * 1_000_000
        if units.denominator != 1:
            raise AccountingError("Unsupported inventory quantity precision")
        return f"{units.numerator // 1_000_000}.{units.numerator % 1_000_000:06d}"
    return {"acquisition_entry_id": acquisition_id, "acquisition_line": acquisition_line,
            "received_quantity": exact_quantity(Fraction(source.quantity)), "received_value_byn": str(source.amount),
            "remaining_quantity": exact_quantity(quantity), "disposed_quantity": exact_quantity(disposed),
            "production_quantity": exact_quantity(production), "disposals": evidence,
            **({"production_disposals": material_evidence} if verified_material_entries else {}),
            "requires_authenticated_complete_history": True, "posted": False}
