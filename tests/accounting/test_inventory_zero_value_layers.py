from dataclasses import replace
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from modules.accounting.inventory_cost import _valuation_layers, issue_result
from modules.accounting.service import AccountingError
from modules.accounting.zero_value_disposals import (
    AuthenticatedZeroValueDisposal,
    ZeroValueDisposalCommand,
    receipt_digest,
)


def row(entry_id, line_id, day, *, quantity, amount, side="debit", dimensions=None, operation="production_output_transfer"):
    dimensions = dimensions or {"warehouse": "MAIN", "sku": "A", "lot": "L1"}
    return SimpleNamespace(id=entry_id, posting_date=day, operation=operation, source=f"source:{entry_id}", source_version=1), SimpleNamespace(
        id=line_id, account_code="43", dimensions=dimensions, category="asset", cash=False, currency="BYN",
        quantity=None if quantity is None else Decimal(str(quantity)), amount=Decimal(str(amount)), side=side,
    )


def event(entry_id=10, line_id=11, quantity="1.000000", token=30):
    command = ZeroValueDisposalCommand(
        operation="inventory_issue", source="inventory:zero:42", source_version=1, posting_date="2026-10-03",
        policy_id=7, basis_digest="a" * 64, destination_account="20", destination_dimensions={"order": "42"},
        inventory_layers=[{"source_entry_id": entry_id, "source_line_id": line_id, "inventory_account": "43",
                           "inventory_dimensions": {"warehouse": "MAIN", "sku": "A", "lot": "L1"}, "quantity": quantity}],
        explanation="Verified zero-value disposal",
    )
    return AuthenticatedZeroValueDisposal(1, 1, date(2026, 10, 3), token, "chief", command, receipt_digest(1, "chief", command))


def data(quantity):
    return SimpleNamespace(warehouse="MAIN", sku="A", lot="L1", quantity=Decimal(str(quantity)), posting_date=date(2026, 10, 4),
                           account="43", policy_id=7, model_dump=lambda **_: {"quantity": str(quantity)})


def test_specific_replays_zero_disposal_after_negative_correction_and_respects_cutoff():
    origin = row(10, 11, date(2026, 10, 1), quantity=2, amount=100)
    correction = row(20, 21, date(2026, 10, 2), quantity=None, amount=100, side="credit", operation="production_output_cost_correction")
    policy = SimpleNamespace(id=7, inventory_method="specific", normative_verified=False)
    result = issue_result(policy, [origin, correction], 1, data(1), verified_value_lines=frozenset({(20, 21)}), zero_value_disposals=(event(),))
    assert (result["book_quantity"], result["book_value_byn"], result["remaining_quantity"], result["issue_cost_byn"]) == ("1.000000", "0.00", "0.000000", "0.00")
    before = issue_result(policy, [origin, correction], 1, data(1), verified_value_lines=frozenset({(20, 21)}), zero_value_disposals=(event(),), before_registration_token=30)
    assert (before["book_quantity"], before["book_value_byn"]) == ("2.000000", "0.00")


def test_rejects_wrong_source_and_overdraw_of_authenticated_zero_event():
    origin = row(10, 11, date(2026, 10, 1), quantity=2, amount=100)
    correction = row(20, 21, date(2026, 10, 2), quantity=None, amount=100, side="credit", operation="production_output_cost_correction")
    policy = SimpleNamespace(id=7, inventory_method="specific", normative_verified=False)
    with pytest.raises(AccountingError, match="source layer"):
        issue_result(policy, [origin, correction], 1, data(1), verified_value_lines=frozenset({(20, 21)}), zero_value_disposals=(event(entry_id=99),))
    with pytest.raises(AccountingError, match="exhausted"):
        issue_result(policy, [origin, correction], 1, data(1), verified_value_lines=frozenset({(20, 21)}), zero_value_disposals=(event(quantity="3.000000"),))


def test_weighted_average_zero_event_removes_quantity_but_preserves_nonzero_pool_value():
    rows = [row(10, 11, date(2026, 10, 1), quantity=3, amount="0.01"), row(12, 13, date(2026, 10, 2), quantity=3, amount="0.01")]
    layers, evidence = _valuation_layers(rows, {"warehouse": "MAIN", "sku": "A", "lot": "L1"}, date(2026, 10, 4), method="weighted_average", zero_value_disposals=(event(),), organization_id=1)
    assert sum(layer["quantity"] for layer in layers) == 5
    assert sum(layer["amount"] for layer in layers) == Decimal("0.02")
    assert evidence[-1]["receipt_id"] == 1 and evidence[-1]["entry_id"] is None


def test_weighted_average_rejects_guessed_zero_cost_and_mutated_or_duplicate_receipts():
    valued_rows = [row(10, 11, date(2026, 10, 1), quantity=2, amount=100), row(12, 13, date(2026, 10, 2), quantity=2, amount=100)]
    with pytest.raises(AccountingError, match="still carries"):
        _valuation_layers(valued_rows, {"warehouse": "MAIN", "sku": "A", "lot": "L1"}, date(2026, 10, 4), method="weighted_average", zero_value_disposals=(event(),), organization_id=1)
    valid_rows = [row(10, 11, date(2026, 10, 1), quantity=3, amount="0.01"), row(12, 13, date(2026, 10, 2), quantity=3, amount="0.01")]
    changed = event()
    changed.command.explanation = "Changed after authentication"
    with pytest.raises(AccountingError, match="identity or digest changed"):
        _valuation_layers(valid_rows, {"warehouse": "MAIN", "sku": "A", "lot": "L1"}, date(2026, 10, 4), method="weighted_average", zero_value_disposals=(changed,), organization_id=1)
    with pytest.raises(AccountingError, match="identity or digest changed"):
        _valuation_layers(valid_rows, {"warehouse": "MAIN", "sku": "A", "lot": "L1"}, date(2026, 10, 4), method="weighted_average", zero_value_disposals=(event(), event()), organization_id=1)


def test_weighted_rejects_grouped_zero_slice_that_rounds_to_a_cent():
    rows = [row(10, 11, date(2026, 10, 1), quantity=5, amount="0.01")]
    with pytest.raises(AccountingError, match="rounded pool value"):
        _valuation_layers(rows, {"warehouse": "MAIN", "sku": "A", "lot": "L1"}, date(2026, 10, 4), method="weighted_average", zero_value_disposals=(event(quantity="3.000000"),), organization_id=1)


def test_specific_allows_a_partial_zero_rounding_slice_but_not_the_full_cent():
    origin = row(10, 11, date(2026, 10, 1), quantity=3, amount="0.01")
    policy = SimpleNamespace(id=7, inventory_method="specific", normative_verified=False)
    result = issue_result(policy, [origin], 1, data(1), zero_value_disposals=(event(quantity="1.000000"),))
    assert (result["book_quantity"], result["book_value_byn"]) == ("2.000000", "0.01")
    with pytest.raises(AccountingError, match="valued or exhausted"):
        issue_result(policy, [origin], 1, data(1), zero_value_disposals=(event(quantity="3.000000"),))


def test_specific_checks_whole_command_across_same_lot_origins():
    rows = [row(n, n + 1, date(2026, 10, 1), quantity=5, amount="0.01") for n in (10, 12, 14)]
    saved = event()
    payload = saved.command.model_dump(mode="json")
    template = payload["inventory_layers"][0]
    payload["inventory_layers"] = [{**template, "source_entry_id": n, "source_line_id": n + 1} for n in (10, 12, 14)]
    command = ZeroValueDisposalCommand(**payload)
    saved = replace(saved, command=command, digest=receipt_digest(1, "chief", command))
    policy = SimpleNamespace(id=7, inventory_method="specific", normative_verified=False)
    with pytest.raises(AccountingError, match="rounded command cost"):
        issue_result(policy, rows, 1, data(1), zero_value_disposals=(saved,))


@pytest.mark.parametrize("method", ["specific", "fifo", "weighted_average"])
def test_future_zero_disposal_requires_chronological_costing(method):
    origin = row(10, 11, date(2026, 10, 1), quantity=5, amount="0.01")
    request = data(1)
    request.posting_date = date(2026, 10, 2)
    policy = SimpleNamespace(id=7, inventory_method=method, normative_verified=False)
    with pytest.raises(AccountingError, match="later movements"):
        issue_result(policy, [origin], 1, request, zero_value_disposals=(event(),))
    result = issue_result(policy, [origin], 1, request, zero_value_disposals=(event(),), before_registration_token=30)
    assert result["book_quantity"] == "5.000000"
