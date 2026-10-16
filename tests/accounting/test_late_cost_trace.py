from datetime import date

import pytest

from modules.accounting.late_cost_trace import trace_specific_lot
from modules.accounting.schemas import PostingInput
from modules.accounting.service import AccountingError


def history(quantity="4", operation="inventory_issue", account="90.4"):
    dimensions = {"warehouse": "WH", "sku": "SKU", "lot": "LOT", "settlement_document": "INV"}
    base = {"source_version": 1, "document_date": "2026-09-01", "operation_date": "2026-09-01",
            "posting_date": "2026-09-01", "policy_id": 1, "rule_version": "synthetic", "explanation": "Test"}
    acquisition = PostingInput(**base, source="receipt:1", operation="inventory_purchase", lines=[
        {"account": "41", "side": "debit", "amount": "100", "quantity": "10", "dimensions": dimensions},
        {"account": "60", "side": "credit", "amount": "100"}])
    issue = PostingInput(**base, source="issue:1", operation=operation, lines=[
        {"account": account, "side": "debit", "amount": "40", "dimensions": {"order": "CUSTOMER"}},
        {"account": "41", "side": "credit", "amount": "40", "quantity": quantity, "dimensions": dimensions}])
    return [(1, acquisition), (2, issue)]


@pytest.mark.parametrize("operation", ["inventory_issue", "inventory_sale"])
def test_trace_partial_disposal_and_keep_exact_destination(operation):
    result = trace_specific_lot(history(operation=operation), 1, 1, date(2026, 9, 10))
    assert result["remaining_quantity"] == "6.000000" and result["disposed_quantity"] == "4.000000"
    assert result["disposals"][0]["expense_dimensions"] == {"order": "CUSTOMER"}
    assert result["requires_authenticated_complete_history"]


def test_verified_cost_increases_value_without_recounting_acquisition_or_disposal():
    entries = history()
    acquisition = entries[0][1]
    cost = acquisition.model_copy(deep=True)
    cost.operation = "inventory_late_cost"
    cost.lines[0].quantity = None
    from decimal import Decimal

    for line in cost.lines:
        line.amount = Decimal("60")
    second_issue = entries[1][1].model_copy(deep=True)
    second_issue.lines[1].quantity = Decimal("6")
    for line in second_issue.lines:
        line.amount = Decimal("120")
    entries += [(3, cost), (4, second_issue)]
    with pytest.raises(AccountingError, match="verified late-cost receipt"):
        trace_specific_lot(entries, 1, 1, date(2026, 9, 10))
    result = trace_specific_lot(entries, 1, 1, date(2026, 9, 10), verified_cost_entries=frozenset({3}))
    assert result["received_value_byn"] == "100"
    assert result["remaining_quantity"] == "0.000000"
    assert result["disposed_quantity"] == "10.000000"
    assert [row["quantity"] for row in result["disposals"]] == ["4", "6"]


@pytest.mark.parametrize("kind", ["production", "oversold", "another_receipt", "later", "mixed", "duplicate", "missing", "excess_value", "value_without_stock"])
def test_ambiguous_or_unsupported_history_is_not_classified_as_stock(kind):
    entries = history(account="20" if kind == "production" else "90.4", quantity="11" if kind == "oversold" else "4")
    if kind == "another_receipt":
        entries.append((3, entries[0][1]))
    if kind == "later":
        entries[1][1].posting_date = date(2026, 10, 1)
    if kind == "mixed":
        entries[1][1].lines[1].dimensions = {**entries[1][1].lines[1].dimensions, "order": "OTHER"}
    if kind == "duplicate":
        entries.append(entries[0])
    if kind == "missing":
        entries = entries[1:]
    if kind == "excess_value":
        from decimal import Decimal
        for line in entries[1][1].lines:
            line.amount = Decimal("200")
    if kind == "value_without_stock":
        from decimal import Decimal
        entries[1][1].lines[1].quantity = Decimal("10")
    with pytest.raises(AccountingError):
        trace_specific_lot(entries, 1, 1, date(2026, 9, 10))


def test_material_trace_requires_verified_source_and_separates_production():
    entries = history(account="20")
    entries[1][1].source = "production:material:1:reviewed"
    with pytest.raises(AccountingError, match="expense destination"):
        trace_specific_lot(entries, 1, 1, date(2026, 9, 10))
    result = trace_specific_lot(entries, 1, 1, date(2026, 9, 10), verified_material_entries=frozenset({2}))
    assert result["remaining_quantity"] == "6.000000"
    assert result["production_quantity"] == "4.000000"
    assert result["disposed_quantity"] == "0.000000" and result["disposals"] == []
    assert result["production_disposals"][0]["expense_account"] == "20"
    assert result["production_disposals"][0]["expense_dimensions"] == {"order": "CUSTOMER"}
    assert result["posted"] is False


@pytest.mark.parametrize("kind", ["unbound", "sale", "missing", "foreign_lot"])
def test_material_trace_rejects_unrelated_verified_identity(kind):
    entries = history(account="20")
    entries[1][1].source = "production:material:1:reviewed"
    identities = frozenset({2})
    if kind == "unbound":
        entries[1][1].source = "manual:1"
    elif kind == "sale":
        entries[1][1].operation = "inventory_sale"
    elif kind == "missing":
        identities = frozenset({3})
    else:
        entries[1][1].lines[1].dimensions["lot"] = "OTHER"
    with pytest.raises(AccountingError):
        trace_specific_lot(entries, 1, 1, date(2026, 9, 10), verified_material_entries=identities)
