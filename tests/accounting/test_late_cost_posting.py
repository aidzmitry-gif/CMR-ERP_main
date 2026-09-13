from decimal import Decimal, localcontext

import pytest
from pydantic import ValidationError

from modules.accounting.late_cost_posting import ExpenseAccounts, candidate
from modules.accounting.service import AccountingError


def calculated():
    return {"history": {"document": {"currency": "BYN", "amount": "123.45", "supplier": "carrier",
        "contract": "contract", "invoice_reference": "invoice", "document_date": "2026-09-01",
        "operation_date": "2026-09-01"}, "receipt_sources": [{"receipt_id": 1, "version": 1,
        "line_number": 1, "account": "41", "inventory_dimensions": {"warehouse": "W", "sku": "S", "lot": "L"}}]},
        "source_movements_verified": True, "posted": False, "excluded_amount_byn": "23.45",
        "shares": [{"receipt_id": 1, "version": 1, "line_number": 1, "destination": "remaining", "amount_byn": "100.00"}],
        "expense_id": 1, "source_version": 1, "posting_date": "2026-09-02", "policy_id": 1,
        "classification_evidence": "Reviewed source classification"}


def test_vat_and_expense_remain_separate_without_losing_supplier_liability():
    accounts = ExpenseAccounts(settlement_account="60", excluded_costs=[
        {"account": "18", "amount_byn": "20.00", "dimensions": {"counterparty": "carrier"}},
        {"account": "44", "amount_byn": "3.45", "dimensions": {"department": "sales"}}])
    with localcontext() as context:
        context.prec = 2
        posting = candidate(calculated(), accounts)
    assert [line.amount for line in posting.lines] == list(map(Decimal, ["100", "20", "3.45", "123.45"]))
    assert [line.account for line in posting.lines] == ["41", "18", "44", "60"]
    assert posting.lines[2].dimensions == {"department": "sales"}
    assert all(line.quantity is None for line in posting.lines)


@pytest.mark.parametrize("amount", ["23.44", "23.46"])
def test_one_cent_classification_difference_blocks_candidate(amount):
    with pytest.raises(AccountingError, match="covered exactly"):
        candidate(calculated(), ExpenseAccounts(settlement_account="60", excluded_costs=[{"account": "18", "amount_byn": amount}]))


@pytest.mark.parametrize("amount", ["0", "-1", "NaN", 1.1])
def test_invalid_classification_amount_is_not_coerced(amount):
    with pytest.raises(ValidationError):
        ExpenseAccounts(settlement_account="60", excluded_costs=[{"account": "18", "amount_byn": amount}])


def test_exclusion_cannot_be_moved_to_cash():
    with pytest.raises(AccountingError, match="input VAT or expense"):
        candidate(calculated(), ExpenseAccounts(settlement_account="60", excluded_costs=[{"account": "51", "amount_byn": "23.45"}]))


def test_no_excluded_cost_requires_no_extra_line():
    data = calculated()
    data["excluded_amount_byn"] = "0.00"
    data["history"]["document"]["amount"] = "100.00"
    posting = candidate(data, ExpenseAccounts(settlement_account="60"))
    assert len(posting.lines) == 2
    assert posting.lines[0].amount == posting.lines[1].amount == Decimal("100.00")


def test_balanced_classification_does_not_hide_incomplete_capitalized_amount():
    data = calculated()
    data["shares"][0]["amount_byn"] = "99.99"
    with pytest.raises(AccountingError, match="complete source liability"):
        candidate(data, ExpenseAccounts(settlement_account="60", excluded_costs=[{"account": "18", "amount_byn": "23.45"}]))
