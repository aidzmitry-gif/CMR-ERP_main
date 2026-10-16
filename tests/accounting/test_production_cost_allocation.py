from decimal import localcontext
from fractions import Fraction

import pytest
from pydantic import ValidationError

from modules.accounting.production_cost_allocation import (
    ProductionOverheadInput,
    preview_production_overhead,
)


def command(amount='100.01', basis='labor_hours', targets=None):
    return ProductionOverheadInput(amount_byn=amount, basis=basis, rounding='largest_remainder_cent',
        targets=targets or [{'order_id': 3, 'basis_amount': '1'}, {'order_id': 1, 'basis_amount': '1'},
                            {'order_id': 2, 'basis_amount': '1'}, {'order_id': 4, 'basis_amount': '0'}])


@pytest.mark.parametrize('basis', ['labor_hours', 'direct_cost', 'output_quantity'])
def test_exact_distribution_and_stable_ties(basis):
    data = command(basis=basis)
    result = preview_production_overhead(data)
    assert [(s['order_id'], s['amount_byn']) for s in result['shares']] == [
        (1, '33.34'), (2, '33.34'), (3, '33.33'), (4, '0.00')]
    assert sum(Fraction(s['amount_byn']) for s in result['shares']) == Fraction('100.01')
    assert preview_production_overhead(data.model_copy(update={'targets': list(reversed(data.targets))})) == result
    assert result['posted'] is False and result['final_cost_certified'] is False


def test_allocation_independent_of_decimal_context_and_zero_share():
    data = command(amount='999999999999.99', targets=[
        {'order_id': 1, 'basis_amount': '0.000001'}, {'order_id': 2, 'basis_amount': '999999999999.999999'}])
    expected = preview_production_overhead(data)
    with localcontext() as ctx:
        ctx.prec = 3
        assert preview_production_overhead(data) == expected
    assert sum(Fraction(s['amount_byn']) for s in expected['shares']) == Fraction(data.amount_byn)


@pytest.mark.parametrize('targets', [
    [{'order_id': 1, 'basis_amount': '0'}],
    [{'order_id': 1, 'basis_amount': '1'}, {'order_id': 1, 'basis_amount': '2'}],
    [{'order_id': 1, 'basis_amount': '-1'}],
    [{'order_id': True, 'basis_amount': '1'}],
    [{'order_id': 1, 'basis_amount': 1.5}],
    [{'order_id': 1, 'basis_amount': 'NaN'}],
])
def test_invalid_bases_never_fall_back(targets):
    with pytest.raises(ValidationError):
        command(targets=targets)


def test_policy_choices_required_and_direct_cost_cent_precision():
    with pytest.raises(ValidationError):
        ProductionOverheadInput(amount_byn='1.00', targets=[{'order_id': 1, 'basis_amount': '1'}])
    with pytest.raises(ValidationError):
        command(basis='direct_cost', targets=[{'order_id': 1, 'basis_amount': '0.001'}])
