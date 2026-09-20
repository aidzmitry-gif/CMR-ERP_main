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
