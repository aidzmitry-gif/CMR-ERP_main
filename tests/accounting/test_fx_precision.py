"""Documented FX amounts must not depend on a caller's Decimal context."""
from decimal import ROUND_DOWN, ROUND_UP, localcontext

import pytest
from pydantic import ValidationError

from modules.accounting.schemas import LineInput


@pytest.mark.parametrize('precision', [6, 28, 50])
@pytest.mark.parametrize('rounding', [ROUND_DOWN, ROUND_UP])
def test_fx_final_cents_are_context_independent(precision, rounding):
    # Exact product is 3234566.96765433; final half-up cents are 3234566.97.
    payload = dict(account='60', side='credit', amount='3234566.97', currency='USD',
                   original_amount='999999.99', rate='3.234567', rate_scale=1,
                   rate_date='2026-09-01', rate_source='Synthetic documented rate')
    with localcontext() as context:
        context.prec = precision
        context.rounding = rounding
        assert str(LineInput.model_validate(payload).amount) == '3234566.97'
        payload['amount'] = '3234566.96'
        with pytest.raises(ValidationError, match='documented exchange rate'):
            LineInput.model_validate(payload)


def test_fx_default_precision_does_not_round_a_below_half_cent_up():
    # Exact cents have remainder denominator/2 - 1. Decimal precision 28
    # used to erase that difference and incorrectly add one cent.
    payload = dict(account='60', side='credit', amount='500000000000000999.99', currency='USD',
                   original_amount='999999999999999999.99', rate='500000000.000001',
                   rate_scale=1000000000, rate_date='2026-09-01',
                   rate_source='Synthetic boundary rate')
    assert str(LineInput.model_validate(payload).amount) == payload['amount']
    payload['amount'] = '500000000000001000.00'
    with pytest.raises(ValidationError, match='documented exchange rate'):
        LineInput.model_validate(payload)
