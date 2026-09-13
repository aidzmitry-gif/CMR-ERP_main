from types import SimpleNamespace

import pytest

from modules.accounting.late_cost_posting import ExpenseAccounts, candidate
from modules.accounting.late_cost_preview import calculate
from modules.accounting.schemas import LateCostPreviewInput
from modules.accounting.service import AccountingError


def _history(currency="USD"):
    return {
        "basis_digest": "b" * 64,
        "document": {
            "currency": currency,
            "amount": "100.00",
            "supplier": "carrier",
            "contract": "contract",
            "invoice_reference": "invoice",
            "document_date": "2026-09-01",
            "operation_date": "2026-09-01",
        },
        "receipt_sources": [{
            "receipt_id": 1, "version": 1, "line_number": 1, "account": "41",
            "inventory_dimensions": {"warehouse": "W", "sku": "S", "lot": "L"},
        }],
        "lots": [{
            "receipt_id": 1, "version": 1, "line_number": 1,
            "received_quantity": "10", "received_value_byn": "1000.00",
            "remaining_quantity": "10", "disposed_quantity": "0", "production_quantity": "0",
            "disposals": [],
        }],
    }


def _policy(method="specific"):
    return SimpleNamespace(
        id=7,
        inventory_method=method,
        normative_verified=False,
        late_cost_allocation={"basis": "quantity", "rounding": "largest_remainder_cent"},
    )


def _data(**changes):
    payload = {
        "expected_version": 1,
        "policy_id": 7,
        "posting_date": "2026-09-02",
        "capitalizable_amount_byn": "320.00",
        "excluded_amount_byn": "0.00",
        "classification_evidence": "Synthetic explicit FX classification",
        "conversion": {
            "currency": "USD", "rate": "3.2", "rate_scale": 1,
            "rate_date": "2026-09-01", "rate_source": "Synthetic official rate evidence",
        },
    }
    payload.update(changes)
    return LateCostPreviewInput.model_validate(payload)


def test_foreign_late_cost_requires_explicit_conversion_and_preserves_byn_basis():
    calculated = calculate(42, 9, _data(), _policy(), _history())

    assert calculated["source_amount"] == "100.00"
    assert calculated["source_amount_byn"] == "320.00"
    assert calculated["conversion"]["rate_scale"] == 1
    posting = candidate(calculated, ExpenseAccounts(settlement_account="60"))
    assert posting.rule_version == "late-cost-fx-v1"
    assert posting.lines[-1].amount == 320


@pytest.mark.parametrize("method", ["fifo", "weighted_average"])
def test_late_cost_calculation_preserves_policy_selected_valuation_method(method):
    calculated = calculate(42, 9, _data(), _policy(method), _history())
    assert calculated["inventory_method"] == method
    assert calculated["basis_digest"]


def test_foreign_late_cost_without_conversion_is_rejected():
    data = _data(conversion=None)
    with pytest.raises(AccountingError, match="documented accounting conversion"):
        calculate(42, 9, data, _policy(), _history())


def test_conversion_currency_and_date_are_bound_to_source_and_posting():
    with pytest.raises(AccountingError, match="currency"):
        calculate(42, 9, _data(conversion={
            "currency": "EUR", "rate": "3.2", "rate_scale": 1,
            "rate_date": "2026-09-01", "rate_source": "Synthetic official rate evidence",
        }), _policy(), _history())
    with pytest.raises(AccountingError, match="after"):
        calculate(42, 9, _data(conversion={
            "currency": "USD", "rate": "3.2", "rate_scale": 1,
            "rate_date": "2026-09-03", "rate_source": "Synthetic official rate evidence",
        }), _policy(), _history())
