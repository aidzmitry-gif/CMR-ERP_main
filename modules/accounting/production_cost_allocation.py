"""Production overhead arithmetic; callers must authenticate policy and cost bases.

No inferred accounting method, posting, or final cost certification.
"""
from decimal import Decimal
from fractions import Fraction
from typing import Annotated, Literal

from pydantic import BeforeValidator, Field, model_validator

from modules.accounting.schemas import Input, Money, exact

BasisAmount = Annotated[Decimal, BeforeValidator(exact), Field(ge=0, max_digits=24, decimal_places=6)]


class ProductionCostTarget(Input):
    order_id: int = Field(gt=0, strict=True)
    # One pool has one explicitly selected measure. Never substitute another
    # measure for a zero base or assign costs equally without policy authority.
    basis_amount: BasisAmount


class ProductionOverheadInput(Input):
    amount_byn: Money = Field(gt=0)
    basis: Literal['direct_cost', 'labor_hours', 'output_quantity']
    rounding: Literal['largest_remainder_cent']
    targets: list[ProductionCostTarget] = Field(min_length=1, max_length=1000)

    @model_validator(mode='after')
    def validate_targets(self):
        ids = [target.order_id for target in self.targets]
        if len(ids) != len(set(ids)):
            raise ValueError('Each production order must occur once per cost pool')
        if not any(target.basis_amount > 0 for target in self.targets):
            raise ValueError('Production overhead requires a positive allocation base')
        if self.basis == 'direct_cost' and any((Fraction(t.basis_amount) * 100).denominator != 1 for t in self.targets):
            raise ValueError('Direct cost bases must contain whole BYN cents')
        return self


def preview_production_overhead(data: ProductionOverheadInput) -> dict:
    """Allocate one homogeneous pool; stable order IDs break equal remainders.

    WIP and finished output disposition are separate from overhead allocation.
    Output quantities must be comparable under the approved pool policy.
    """
    targets = sorted(data.targets, key=lambda target: target.order_id)
    cents = Fraction(data.amount_byn) * 100
    if cents.denominator != 1:
        raise ValueError('Overhead amount must contain whole cents')
    total_basis = sum(Fraction(target.basis_amount) for target in targets)
    shares = []
    for target in targets:
        quota = cents * Fraction(target.basis_amount) / total_basis
        floor = quota.numerator // quota.denominator
        shares.append([target, floor, quota - floor])
    remaining = cents.numerator - sum(share[1] for share in shares)
    for index in sorted(range(len(shares)), key=lambda index: -shares[index][2])[:remaining]:
        shares[index][1] += 1

    def money(value):
        return f'{value // 100}.{value % 100:02d}'

    return {'amount_byn': money(cents.numerator), 'basis': data.basis, 'rounding': data.rounding,
        'shares': [{'order_id': target.order_id, 'basis_amount': format(target.basis_amount, '.6f'),
                    'amount_byn': money(amount)} for target, amount, _ in shares],
        'status': 'arithmetic_preview', 'posted': False, 'source_movements_verified': False,
        'final_cost_certified': False}
