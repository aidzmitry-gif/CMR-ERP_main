"""Pure replay refuses untrusted identities, valued zero-disposals and overdraw.

Synthetic sealed objects exercise in-memory admission, not DB authentication,
production stock or device acceptance. No stock mutation or write is performed.
"""
from copy import deepcopy
from dataclasses import replace
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from modules.accounting import inventory_allocation_loader as loader
from modules.accounting import inventory_cost as cost
from modules.accounting.service import AccountingError
from modules.accounting.zero_value_disposals import receipt_digest
from tests.accounting.test_inventory_zero_value_layers import (
    data,
    event,
    projection_pool,
    projection_selection,
    row,
)

TARGET = {"warehouse": "MAIN", "sku": "A", "lot": "L1"}
DAY = date(2026, 10, 4)


@pytest.mark.parametrize("field, value, message", [
    ("dimensions", {"warehouse": "MAIN", "sku": "A"}, "without warehouse, SKU or lot"),
    ("category", "liability", "not owned inventory"),
    ("cash", True, "not owned inventory"),
    ("currency", "USD", "Foreign-currency inventory"),
    ("quantity", None, "needs quantity"),
    ("quantity", Decimal("0"), "must be positive"),
    ("quantity", Decimal("-1"), "must be positive"),
    ("amount", Decimal("0"), "must be positive"),
])
def test_layer_admission_refuses_incomplete_or_nonowned_inventory(field, value, message):
    entry, line = row(10, 11, date(2026, 10, 1), quantity=3, amount=10)
    setattr(line, field, value)
    original = deepcopy(vars(entry)), deepcopy(vars(line))
    with pytest.raises(AccountingError) as error:
        cost._valuation_layers([(entry, line)], TARGET, DAY)
    assert message in str(error.value)
    assert (vars(entry), vars(line)) == original


def test_unverified_finished_goods_are_not_an_owned_acquisition_layer():
    rows = [row(10, 11, date(2026, 10, 1), quantity=3, amount=10)]
    with pytest.raises(AccountingError) as error:
        cost._valuation_layers(rows, TARGET, DAY, finished_goods=True)
    assert "no verified production output receipt" in str(error.value)
    accepted, _ = cost._valuation_layers(rows, TARGET, DAY, finished_goods=True,
                                         verified_output_lines=frozenset({(10, 11)}))
    assert len(accepted) == 1 and accepted[0]["quantity"] == Decimal("3")


def test_later_movement_of_same_sku_blocks_backdated_costing_without_mixing_other_sku():
    entry, line = row(10, 11, date(2026, 10, 5), quantity=3, amount=10)
    with pytest.raises(AccountingError) as error:
        cost._valuation_layers([(entry, line)], TARGET, DAY)
    assert "chronological costing is required" in str(error.value)
    line.dimensions = {**line.dimensions, "sku": "OTHER"}
    assert cost._valuation_layers([(entry, line)], TARGET, DAY) == ([], [])


@pytest.mark.parametrize("calculator", [cost._valuation_layers, cost._lot_balance])
def test_zero_value_disposal_replay_requires_explicit_organization(calculator):
    with pytest.raises(AccountingError) as error:
        calculator([], TARGET, DAY, zero_value_disposals=(event(),))
    assert str(error.value) == "Zero-value disposal replay needs an organization identity"


@pytest.mark.parametrize("problem", ["untyped", "foreign_book"])
def test_untyped_or_cross_book_zero_disposal_is_not_authenticated(problem):
    original = event()
    receipt = SimpleNamespace() if problem == "untyped" else replace(
        original, organization_id=2, digest=receipt_digest(2, original.actor, original.command),
    )
    with pytest.raises(AccountingError) as error:
        cost._chronological_events([], 1, DAY, [receipt])
    assert "provenance is not authenticated" in str(error.value)


def _disposition(*, organization_id=1, line_ids=(200,)):
    allocation = loader.InventoryDispositionAllocation.model_validate({
        "allocation_version": 1, "valuation_method": "fifo", "quantity": "1", "amount_byn": "1.00",
        "layers": [{"source_entry_id": 10, "source_line_id": 11, "inventory_account": "43",
                    "inventory_dimensions": TARGET, "quantity": "1", "amount_byn": "1.00"}],
    })
    values = (100, 100, organization_id, date(2026, 10, 3), "synthetic:issue", 1, allocation, line_ids)
    return loader.AuthenticatedInventoryDisposition(
        *values, loader._snapshot_digest(loader._snapshot(*values)),
    )


@pytest.mark.parametrize("problem, message", [
    ("untyped", "unsupported type"), ("foreign_book", "not authenticated for this organization"),
    ("credit_count", "replacement count changed"), ("missing_credit", "replacement line is missing"),
])
def test_allocation_event_cannot_claim_an_unverified_ledger_replacement(problem, message):
    disposition = SimpleNamespace() if problem == "untyped" else _disposition(
        organization_id=2 if problem == "foreign_book" else 1,
        line_ids=() if problem == "credit_count" else (200,),
    )
    with pytest.raises(AccountingError) as error:
        cost._chronological_events([], 1, DAY, (), authenticated_dispositions=(disposition,))
    assert message in str(error.value)


@pytest.mark.parametrize("field, value, entry_field", [
    ("source", "synthetic:other", True), ("source_version", 2, True),
    ("posting_date", date(2026, 10, 2), True),
    ("side", "debit", False), ("account_code", "10.1", False),
    ("quantity", Decimal("2"), False), ("amount", Decimal("2"), False),
    ("dimensions", {"warehouse": "OTHER", "sku": "A", "lot": "L1"}, False),
    ("currency", "USD", False), ("category", "liability", False), ("cash", True, False),
])
def test_replacement_credit_must_match_every_original_ledger_identity(field, value, entry_field):
    disposition = _disposition()
    entry, line = row(100, 200, date(2026, 10, 3), quantity=1, amount=1, side="credit")
    entry.source, entry.source_version = "synthetic:issue", 1
    setattr(entry if entry_field else line, field, value)
    original = deepcopy(vars(entry)), deepcopy(vars(line))
    with pytest.raises(AccountingError) as error:
        cost._chronological_events([(entry, line)], 1, DAY, (), authenticated_dispositions=(disposition,))
    assert str(error.value) == "Inventory allocation replacement line changed"
    assert (vars(entry), vars(line)) == original


@pytest.mark.parametrize("options", [{"inventory_account": "10.1"}, {"before_registration_token": 100}])
def test_replay_boundary_skips_other_account_or_not_yet_registered_event(options):
    assert cost._chronological_events([], 1, DAY, (), authenticated_dispositions=(_disposition(),), **options) == []


@pytest.mark.parametrize("amount", [Decimal("-0.01"), Decimal("0.001")])
def test_weighted_pool_never_accepts_negative_value_or_fractional_cents(amount):
    layers = [{"quantity": Decimal(1), "amount": Decimal(1)}]
    original = deepcopy(layers)
    with pytest.raises(AccountingError) as error:
        cost._distribute_pool_value(layers, amount)
    assert "invalid remaining book value" in str(error.value) and layers == original


def test_exhausted_weighted_pool_cannot_hide_remaining_value():
    with pytest.raises(AccountingError) as error:
        cost._distribute_pool_value([{"quantity": Decimal(0), "amount": Decimal(0)}], Decimal("0.01"))
    assert str(error.value) == "Empty inventory pool retains book value"


def test_duplicate_origin_and_excess_monetary_allocation_are_refused_without_pool_mutation():
    first = projection_pool()[0]
    selection = projection_selection([first], "fifo", ["1"], ["6.25"])
    duplicated = [deepcopy(first), deepcopy(first)]
    with pytest.raises(AccountingError) as duplicate:
        cost.replay_source_allocation(duplicated, selection)
    assert str(duplicate.value) == "Inventory history repeats an origin"
    assert duplicated == [first, first]
    pool = [{**first, "amount": Decimal("10.00")}]
    selection = projection_selection(pool, "fifo", ["1"], ["20.00"])
    with pytest.raises(AccountingError) as excess:
        cost.replay_source_allocation(pool, selection)
    assert "exceeds the available quantity or cost" in str(excess.value)
    assert pool[0]["quantity"] == first["quantity"] and pool[0]["amount"] == Decimal("10.00")


@pytest.mark.parametrize("problem, message", [
    ("specific_identity", "requires FIFO or weighted-average layer selection"),
    ("specific_no_lot", "requires an explicit lot"),
    ("unsupported_method", "valuation method is not supported"),
])
def test_issue_requires_explicit_supported_valuation_scope(problem, message):
    policy = SimpleNamespace(id=7, inventory_method="lifo" if problem == "unsupported_method" else "specific")
    request = data(1)
    if problem == "specific_no_lot":
        request.lot = ""
    with pytest.raises(AccountingError) as error:
        cost.issue_result(policy, [row(10, 11, date(2026, 10, 1), quantity=3, amount=10)], 1, request,
                          include_source_identity=problem == "specific_identity")
    assert message in str(error.value)
