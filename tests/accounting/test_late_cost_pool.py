from datetime import date
from decimal import Decimal

import pytest

from modules.accounting.inventory_allocation_loader import (
    AuthenticatedInventoryDisposition,
    _snapshot,
    _snapshot_digest,
)
from modules.accounting.late_cost_pool import project_pool
from modules.accounting.service import AccountingError
from tests.accounting.test_inventory_zero_value_layers import (
    allocation_event,
    projection_pool,
    projection_selection,
    row,
)


def history(method):
    sources = projection_pool()
    rows = [row(item["entry_id"], item["line_id"], date(2026, 10, index + 1),
        quantity=item["quantity"], amount=item["amount"], dimensions=item["dimensions"],
        operation="inventory_purchase") for index, item in enumerate(sources)]
    amounts = ["31.25", "10.00"] if method == "fifo" else ["38.28", "7.66"]
    allocation = projection_selection(sources, method, ["5", "1"], amounts)
    for index, layer in enumerate(allocation.layers):
        rows.append(row(30, 31 + index, date(2026, 10, 3), quantity=layer.quantity,
            amount=layer.amount_byn, dimensions=layer.inventory_dimensions, side="credit", operation="inventory_issue"))
    for _, line in rows:
        line.account_code = "10.1"
    snapshot = _snapshot(30, 30, 1, date(2026, 10, 3), "source:30", 1, allocation, (31, 32))
    event = AuthenticatedInventoryDisposition(30, 30, 1, date(2026, 10, 3), "source:30", 1,
        allocation, (31, 32), _snapshot_digest(snapshot))
    return rows, event


def project(rows, **changes):
    kwargs = dict(organization_id=1, account="10.1", warehouse="MAIN", sku="A",
        on=date(2026, 10, 4), additions={(10, 11): Decimal("5.00")})
    return project_pool(rows, **(kwargs | changes))


@pytest.mark.parametrize("method,disposed,remaining", [("fifo", "5.00", "0.00"),
                                                        ("weighted_average", "3.75", "1.25")])
def test_complete_history_moves_cost_to_actual_surviving_origin(method, disposed, remaining):
    rows, event = history(method)
    result = project(rows, method=method, dispositions=(event,))
    assert result["movements"][0]["delta_byn"] == disposed
    assert result["movements"][0]["kind"] == "entry"
    assert result["movements"][0]["entry_id"] == 30
    assert len(result["remaining"]) == 1
    assert result["remaining"][0]["source_entry_id"] == 20
    assert result["remaining"][0]["dimensions"]["lot"] == "L2"
    assert result["remaining"][0]["delta_byn"] == remaining
    assert result["posted"] is False


@pytest.mark.parametrize("method", ["fifo", "weighted_average"])
def test_entryless_projection_retains_receipt_identity(method):
    rows = [row(10, 11, date(2026, 10, 1), quantity=100, amount="0.01", operation="inventory_purchase")]
    rows[0][1].account_code = "10.1"
    zero = allocation_event(method=method, account="10.1", layers=[{
        "source_entry_id": 10, "source_line_id": 11, "inventory_account": "10.1",
        "inventory_dimensions": rows[0][1].dimensions, "quantity": "1"}])
    result = project(rows, method=method, zeros=(zero,), additions={(10, 11): Decimal("1.00")})
    movement, = result["movements"]
    assert movement["kind"] == "zero_receipt" and movement["receipt_id"] == zero.receipt_id
    assert "entry_id" not in movement
    assert movement["delta_byn"] == "0.01"
    assert result["remaining"][0]["delta_byn"] == "0.99"


def test_projection_requires_complete_allocation_and_chronological_history():
    rows, event = history("fifo")
    with pytest.raises(AccountingError, match="missing"):
        project(rows[:-1], method="fifo", dispositions=(event,))
    with pytest.raises(AccountingError, match="without authenticated"):
        project(rows, method="fifo")
    with pytest.raises(AccountingError, match="later movements"):
        project(rows, method="fifo", dispositions=(event,), on=date(2026, 10, 2))
    historical = project(rows, method="fifo", dispositions=(event,), before_token=30)
    assert historical["movements"] == []
    assert sum(Decimal(item["delta_byn"]) for item in historical["remaining"]) == Decimal("5.00")


def test_overlay_cannot_refer_to_missing_or_unrelated_acquisition():
    rows, event = history("fifo")
    with pytest.raises(AccountingError, match="missing"):
        project(rows, method="fifo", dispositions=(event,), additions={(999, 998): Decimal("5.00")})
    rows[0][0].operation = "manual"
    with pytest.raises(AccountingError, match="inventory purchase"):
        project(rows, method="fifo", dispositions=(event,))


def expense_input(method, basis):
    from modules.accounting.schemas import LateCostPreviewInput

    rows, event = history(method)
    loaded = {"policy_id": 7, "on": "2026-10-04", "method": method,
        "rule": {"basis": basis, "rounding": "largest_remainder_cent"},
        "normative_verified": False, "basis_digest": "a" * 64, "before_registration_token": None,
        "source": {"organization_id": 1, "expense_id": 42, "version": 1,
            "document": {"currency": "BYN", "amount": "6.00", "supplier": "carrier", "contract": "freight",
                "invoice_reference": "F42", "document_date": "2026-10-04", "operation_date": "2026-10-04"}},
        "origins": {(1, 1, 1): (10, 11), (2, 1, 1): (20, 21)},
        "pools": [{"account": "10.1", "warehouse": "MAIN", "sku": "A", "rows": rows,
            "dispositions": (event,), "zeros": (), "verified_values": frozenset(),
            "destinations": {("entry", 30): {"account": "20", "dimensions": {"order": "ORDER-42"},
                "source": "source:30", "source_version": 1}}}]}
    request = LateCostPreviewInput(expected_version=1, policy_id=7, posting_date="2026-10-04",
        capitalizable_amount_byn="5.00", excluded_amount_byn="1.00", classification_evidence="Synthetic reviewed freight")
    return loaded, request


@pytest.mark.parametrize("method", ["fifo", "weighted_average"])
@pytest.mark.parametrize("basis,apportionment", [("quantity", ["3.13", "1.87"]),
                                                ("received_value", ["2.55", "2.45"])])
def test_document_policy_apportions_all_sources_then_builds_balanced_candidate(method, basis, apportionment):
    from modules.accounting.late_cost_pool import calculate_expense
    from modules.accounting.late_cost_posting import ExpenseAccounts, pool_candidate

    loaded, request = expense_input(method, basis)
    result = calculate_expense(loaded, request)
    assert [row["amount_byn"] for row in result["source_apportionment"]] == apportionment
    assert result["source_amount_byn"] == "6.00" and result["confirmation_available"] is False
    assert sum(Decimal(row["delta_byn"]) for row in result["destinations"]) == Decimal("5.00")
    posting = pool_candidate(result, ExpenseAccounts(settlement_account="60", excluded_costs=[{
        "account": "18", "amount_byn": "1.00", "dimensions": {"supplier": "carrier"}}]))
    assert sum(line.amount for line in posting.lines if line.side == "debit") == Decimal("6.00")
    assert sum(line.amount for line in posting.lines if line.side == "credit") == Decimal("6.00")
    assert posting.lines[-1].dimensions["settlement_document"] == "F42"
    assert posting.rule_version == "late-cost-pool-v3"


def test_full_expense_rejects_missing_policy_wrong_coverage_and_changed_calculation():
    from modules.accounting.late_cost_pool import calculate_expense
    from modules.accounting.late_cost_posting import ExpenseAccounts, pool_candidate

    loaded, request = expense_input("fifo", "quantity")
    with pytest.raises(AccountingError, match="policy"):
        calculate_expense({**loaded, "rule": None}, request)
    with pytest.raises(AccountingError, match="cover the source"):
        calculate_expense(loaded, request.model_copy(update={"capitalizable_amount_byn": Decimal("4.99")}))
    result = calculate_expense(loaded, request)
    result["destinations"][0]["delta_byn"] = "4.99"
    with pytest.raises(AccountingError, match="unchanged"):
        pool_candidate(result, ExpenseAccounts(settlement_account="60"))


def test_one_cent_expense_preserves_signed_weighted_remainder_redistribution():
    from modules.accounting.late_cost_pool import calculate_expense
    from modules.accounting.late_cost_posting import ExpenseAccounts, pool_candidate

    loaded, request = expense_input("weighted_average", "quantity")
    rows = [row(index * 10, index * 10 + 1, date(2026, 10, index), quantity=quantity, amount="0.01",
        dimensions={"warehouse": "MAIN", "sku": "A", "lot": f"L{index}"}, operation="inventory_purchase")
        for index, quantity in enumerate((1, 3, 3), 1)]
    for _, line in rows:
        line.account_code = "10.1"
    loaded["origins"] = {(1, 1, 1): (10, 11)}
    loaded["source"]["document"]["amount"] = "0.01"
    loaded["pools"][0].update(rows=rows, dispositions=(), destinations={})
    request = request.model_copy(update={"capitalizable_amount_byn": Decimal("0.01"),
                                         "excluded_amount_byn": Decimal("0.00")})
    result = calculate_expense(loaded, request)
    assert [item["delta_byn"] for item in result["destinations"]] == ["-0.01", "0.01", "0.01"]
    posting = pool_candidate(result, ExpenseAccounts(settlement_account="60"))
    assert [(line.account, line.side, line.amount) for line in posting.lines] == [
        ("10.1", "credit", Decimal("0.01")), ("10.1", "debit", Decimal("0.01")),
        ("10.1", "debit", Decimal("0.01")), ("60", "credit", Decimal("0.01"))]
