from decimal import Decimal, localcontext

import pytest
from pydantic import ValidationError

from modules.accounting.late_cost_allocation import AllocationInput, preview_allocation


def lot(**changes):
    return {"receipt_id": 1, "version": 1, "line_number": 1, "received_quantity": "10",
            "received_value_byn": "1000.00", "remaining_quantity": "6", "disposed_quantity": "4",
            "production_quantity": "0", **changes}


def request(**changes):
    return AllocationInput.model_validate({"amount_byn": "100.00", "basis": "quantity",
        "rounding": "largest_remainder_cent", "lots": [lot()], **changes})


def test_partial_issue_does_not_charge_full_expense_to_remaining_stock():
    result = preview_allocation(request())
    assert result["totals_byn"] == {"remaining": "60.00", "disposed": "40.00", "production": "0.00"}
    assert not result["posted"] and not result["final_cost_certified"] and not result["source_movements_verified"]


def test_production_share_remains_separate_and_no_stock_remaining_is_valid():
    result = preview_allocation(request(lots=[lot(remaining_quantity="0", disposed_quantity="4", production_quantity="6")]))
    assert result["totals_byn"] == {"remaining": "0.00", "disposed": "40.00", "production": "60.00"}


def test_explicit_value_basis_differs_from_quantity_basis():
    lots = [lot(remaining_quantity="10", disposed_quantity="0"),
            lot(receipt_id=2, received_value_byn="3000", remaining_quantity="0", disposed_quantity="10")]
    assert preview_allocation(request(lots=lots))["totals_byn"]["remaining"] == "50.00"
    assert preview_allocation(request(lots=lots, basis="received_value"))["totals_byn"]["remaining"] == "25.00"


def test_one_cent_many_destinations_is_conserved_and_input_order_independent():
    lots = [lot(receipt_id=i, received_quantity="3", remaining_quantity="1", disposed_quantity="1", production_quantity="1") for i in range(1, 4)]
    first = preview_allocation(request(amount_byn="0.01", lots=lots))
    assert first == preview_allocation(request(amount_byn="0.01", lots=list(reversed(lots))))
    assert sum(Decimal(row["amount_byn"]) for row in first["shares"]) == Decimal("0.01")
    assert first["shares"][0]["amount_byn"] == "0.01"


def test_large_exact_values_ignore_global_decimal_precision():
    data = request(amount_byn="999999999999999999.99")
    expected = preview_allocation(data)
    with localcontext() as context:
        context.prec = 6
        assert preview_allocation(data) == expected
    assert sum(Decimal(row["amount_byn"]) for row in expected["shares"]) == Decimal(data.amount_byn)


@pytest.mark.parametrize("changes", [{"basis": None}, {"rounding": None}, {"amount_byn": 1.1},
    {"amount_byn": "NaN"}, {"amount_byn": "0"}, {"lots": []}, {"lots": [lot(), lot()]},
    {"lots": [lot(remaining_quantity="7")]}, {"lots": [lot(disposed_quantity="-1")]},
    {"lots": [lot(received_quantity=True)]}, {"lots": [lot(received_value_byn="0")]}])
def test_invalid_or_incomplete_basis_is_not_replaced_with_defaults(changes):
    with pytest.raises(ValidationError):
        request(**changes)
