from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from modules.accounting.inventory_cost import _lot_balance, issue_result
from modules.accounting.service import AccountingError

TARGET = {"warehouse": "W", "sku": "S", "lot": "L"}


def movement(identity, quantity, amount, side="debit", operation="inventory_purchase", **changes):
    entry = SimpleNamespace(id=identity, source=f"source:{identity}", source_version=1,
                            posting_date=date(2026, 9, 1), operation=operation)
    line = SimpleNamespace(id=identity, quantity=None if quantity is None else Decimal(quantity),
        amount=Decimal(amount), side=side, dimensions=TARGET.copy(), category="asset", cash=False, currency="BYN")
    for key, value in changes.items():
        setattr(line, key, value)
    return entry, line


def history():
    return [movement(1, "10", "1000"), movement(2, "4", "400", "credit", "inventory_issue"),
            movement(3, None, "60", operation="inventory_late_cost")]


def test_value_increases_without_quantity_and_next_issue_uses_it():
    rows = history()
    policy = SimpleNamespace(id=1, normative_verified=False)
    request = SimpleNamespace(warehouse="W", sku="S", lot="L", posting_date=date(2026, 9, 1),
        quantity=Decimal("2"), account="41", model_dump=lambda **_: {"quantity": "2"})
    result = issue_result(policy, rows, 1, request, verified_value_lines={(3, 3)})
    assert result["book_quantity"] == "6.000000"
    assert result["book_value_byn"] == "660.00"
    assert result["issue_cost_byn"] == "220.00"
    assert result["remaining_value_byn"] == "440.00"
    assert result["evidence"][-1]["quantity"] is None
    rows.append(movement(4, "6", "660", "credit", "inventory_issue"))
    quantity, amount, _, _ = _lot_balance(rows, TARGET, date(2026, 9, 1), verified_value_lines={(3, 3)})
    assert quantity == amount == 0


def test_unverified_value_line_still_blocks_every_existing_caller():
    with pytest.raises(AccountingError, match="no quantity"):
        _lot_balance(history(), TARGET, date(2026, 9, 1))


@pytest.mark.parametrize("changes", [{"quantity": Decimal("1")}, {"side": "credit"},
    {"amount": Decimal("0")}, {"cash": True}, {"currency": "USD"}, {"dimensions": {**TARGET, "contract": "other"}}])
def test_invalid_adjustment_cannot_be_admitted_by_identity_alone(changes):
    rows = history()
    for key, value in changes.items():
        setattr(rows[-1][1], key, value)
    with pytest.raises(AccountingError):
        _lot_balance(rows, TARGET, date(2026, 9, 1), verified_value_lines={(3, 3)})


def test_cost_cannot_remain_on_an_empty_lot():
    rows = [movement(1, "10", "1000"), movement(2, "10", "1000", "credit", "inventory_issue"), history()[-1]]
    with pytest.raises(AccountingError, match="Invalid verified"):
        _lot_balance(rows, TARGET, date(2026, 9, 1), verified_value_lines={(3, 3)})


def test_new_acquisition_after_adjustment_requires_layer_separation():
    with pytest.raises(AccountingError, match="separate lot layers"):
        _lot_balance([*history(), movement(4, "1", "100")], TARGET, date(2026, 9, 1), verified_value_lines={(3, 3)})
