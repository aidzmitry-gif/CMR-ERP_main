from decimal import localcontext

import pytest

from modules.accounting.production_cost_correction import correction_delta
from modules.accounting.service import AccountingError


def allocation(amount, order='A', department='SHOP'):
    return [{'account': '20', 'side': 'debit', 'amount': amount, 'dimensions': {'department': department, 'order': order}},
        {'account': '25', 'side': 'credit', 'amount': amount, 'dimensions': {'department': department}}]


def test_delta_increases_decreases_and_zero_difference_without_duplicate_allocation():
    assert correction_delta(allocation('30.00'), allocation('31.01')) == allocation('1.01')
    assert correction_delta(allocation('30.00'), allocation('29.99')) == [
        {**allocation('0.01')[0], 'side': 'credit'}, {**allocation('0.01')[1], 'side': 'debit'}]
    assert correction_delta(allocation('30.00'), allocation('30.00')) == []
    assert correction_delta(allocation('30.00'), []) == [
        {**allocation('30.00')[0], 'side': 'credit'}, {**allocation('30.00')[1], 'side': 'debit'}]


def test_delta_preserves_full_analytics_and_exact_large_values():
    with localcontext() as context:
        context.prec = 3
        assert correction_delta(allocation('999999999999999999.98'), allocation('999999999999999999.99')) == allocation('0.01')
        moved = correction_delta(allocation('30.00'), allocation('30.00', order='B'))
    assert moved == [{**allocation('30.00')[0], 'side': 'credit'}, allocation('30.00', order='B')[0]]
    moved_pool = correction_delta(allocation('30.00'), allocation('30.00', department='OTHER'))
    assert len(moved_pool) == 4  # Pool credits cannot cancel across different departments.


@pytest.mark.parametrize('amount', ['-1.00', '0.001'])
def test_delta_rejects_inexact_or_negative_amounts(amount):
    with pytest.raises(AccountingError):
        correction_delta(allocation('1.00'), allocation(amount))


def test_delta_rejects_an_unbalanced_target():
    with pytest.raises(AccountingError, match='balance'):
        correction_delta(allocation('1.00'), allocation('1.00')[:1])
