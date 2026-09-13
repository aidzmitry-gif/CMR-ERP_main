from decimal import localcontext

import pytest

from modules.accounting.late_cost_disposals import disposal_shares
from modules.accounting.service import AccountingError


def row(entry, quantity="1", account="90.4"):
    return {"entry_id": entry, "inventory_line": 2, "quantity": quantity,
            "expense_account": account, "expense_dimensions": {"order": str(entry)},
            "source": f"issue:{entry}", "source_version": 1}


def test_split_preserves_original_accounts_analytics_and_total():
    result = disposal_shares("40.00", "4", [row(1, "1"), row(2, "3", "44")])
    assert [item["amount_byn"] for item in result] == ["10.00", "30.00"]
    assert result[1] == {**row(2, "3", "44"), "amount_byn": "30.00"}


def test_cent_tie_is_stable_under_reordered_history_and_decimal_context():
    rows = [row(3), row(1), row(2)]
    with localcontext() as context:
        context.prec = 2
        result = disposal_shares("0.02", "3", rows)
    assert result == disposal_shares("0.02", "3", list(reversed(rows)))
    assert [item["amount_byn"] for item in result] == ["0.01", "0.01", "0.00"]


@pytest.mark.parametrize("amount,quantity,rows", [
    ("1.00", "2", [row(1)]), ("1.00", "2", [row(1), row(1)]),
    ("1.00", "0", []), ("0.001", "1", [row(1)]),
    ("-1.00", "1", [row(1)]), ("1.00", "0", [row(1, "0")]),
    ("1.00", "1", [row(True)]),
])
def test_incomplete_or_invalid_disposal_cannot_be_allocated(amount, quantity, rows):
    with pytest.raises(AccountingError):
        disposal_shares(amount, quantity, rows)


def test_no_disposal_is_explicitly_empty():
    assert disposal_shares("0.00", "0", []) == []
