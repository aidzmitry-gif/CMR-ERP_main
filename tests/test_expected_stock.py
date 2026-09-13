import pytest

from modules.procurement.expected_stock import project_line


def test_client_allocations_free_expected_and_partial_conversion():
    rows = [{"allocation_id": "client-A", "allocated": "60", "released": "0", "converted": "0"}]
    assert project_line(ordered="100", accepted="0", cancelled="0", allocations=rows)["free_expected"] == "40.00"
    rows.append({"allocation_id": "client-B", "allocated": "15", "released": "0", "converted": "0"})
    assert project_line(ordered="100", accepted="0", cancelled="0", allocations=rows)["free_expected"] == "25.00"
    rows[0]["converted"] = "20"
    result = project_line(ordered="100", accepted="20", cancelled="0", allocations=rows)
    assert (result["expected"], result["expected_reserved"], result["free_expected"]) == ("80.00", "55.00", "25.00")
    rows[1]["released"] = "15"
    assert project_line(ordered="100", accepted="20", cancelled="0", allocations=rows)["free_expected"] == "40.00"


def test_supplier_reduction_exposes_uncovered_clients():
    row = {"allocation_id": "A", "allocated": "60", "released": "0", "converted": "0"}
    result = project_line(ordered="100", accepted="0", cancelled="50", allocations=[row])
    assert result["uncovered"] == "10.00" and result["free_expected"] == "0.00"
    assert not result["allocation_allowed"] and result["clients"][0]["expected_reserved"] == "60.00"


@pytest.mark.parametrize("value", [None, 1, "NaN", "Infinity", "-1", "0.001", "1e2", ""])
def test_unknown_or_invalid_quantity_never_becomes_zero(value):
    with pytest.raises(ValueError):
        project_line(ordered="100", accepted=value, cancelled="0", allocations=[])


def test_conversion_requires_actual_acceptance_and_unique_allocation():
    row = {"allocation_id": "A", "allocated": "10", "released": "0", "converted": "5"}
    with pytest.raises(ValueError, match="accepted"):
        project_line(ordered="100", accepted="0", cancelled="0", allocations=[row])
    with pytest.raises(ValueError, match="repeated"):
        project_line(ordered="100", accepted="10", cancelled="0", allocations=[row, row])
