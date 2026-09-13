"""Exact late-cost allocation arithmetic, awaiting authenticated movement wiring.

No policy defaults, source discovery, ledger writes or final-cost certification.
"""
from decimal import Decimal
from fractions import Fraction
from typing import Annotated, Literal

from pydantic import BeforeValidator, Field, model_validator

from modules.accounting.schemas import Input, Money, Quantity, exact

NonnegativeQuantity = Annotated[Decimal, BeforeValidator(exact), Field(ge=0, max_digits=24, decimal_places=6)]


class AllocationLot(Input):
    receipt_id: int = Field(gt=0, strict=True)
    version: int = Field(gt=0, strict=True)
    line_number: int = Field(gt=0, strict=True)
    received_quantity: Quantity
    received_value_byn: Money = Field(gt=0)
    remaining_quantity: NonnegativeQuantity
    disposed_quantity: NonnegativeQuantity
    production_quantity: NonnegativeQuantity

    @model_validator(mode="after")
    def complete_quantity(self):
        # Fraction avoids dependence on the process-wide Decimal precision.
        if sum(Fraction(value) for value in (self.remaining_quantity, self.disposed_quantity,
                                           self.production_quantity)) != Fraction(self.received_quantity):
            raise ValueError("Remaining, disposed and production quantities must cover the receipt exactly")
        return self


class AllocationInput(Input):
    amount_byn: Money = Field(gt=0)
    basis: Literal["quantity", "received_value"]
    rounding: Literal["largest_remainder_cent"]
    lots: list[AllocationLot] = Field(min_length=1, max_length=300)

    @model_validator(mode="after")
    def unique_sources(self):
        keys = [(lot.receipt_id, lot.version, lot.line_number) for lot in self.lots]
        if len(keys) != len(set(keys)):
            raise ValueError("Every receipt source line must occur once")
        return self


def preview_allocation(data: AllocationInput):
    """Distribute integer cents across receipt/destination pairs without loss.

    Each original receipt's basis is split by its quantity disposition. Equal
    remainders use canonical source ID then destination order, never input order.
    The caller must derive quantities from verified ledger movements and approve
    this explicit basis/rounding rule under the applicable versioned policy.
    """
    lots = sorted(data.lots, key=lambda lot: (lot.receipt_id, lot.version, lot.line_number))
    weights = [Fraction(lot.received_quantity if data.basis == "quantity" else lot.received_value_byn) for lot in lots]
    total_weight = sum(weights)
    total_cents = Fraction(data.amount_byn) * 100
    if total_cents.denominator != 1:
        raise ValueError("Allocation amount must contain whole cents")
    shares = []
    for lot, weight in zip(lots, weights, strict=True):
        for destination, quantity in (("remaining", lot.remaining_quantity), ("disposed", lot.disposed_quantity),
                                      ("production", lot.production_quantity)):
            quota = total_cents * weight * Fraction(quantity) / Fraction(lot.received_quantity) / total_weight
            cents = quota.numerator // quota.denominator
            shares.append({"receipt_id": lot.receipt_id, "version": lot.version, "line_number": lot.line_number,
                           "destination": destination, "quantity": format(quantity, ".6f"),
                           "cents": cents, "remainder": quota - cents})
    residual = total_cents.numerator - sum(share["cents"] for share in shares)
    for index in sorted(range(len(shares)), key=lambda index: -shares[index]["remainder"])[:residual]:
        shares[index]["cents"] += 1
    # Formatting integer cents also stays independent of Decimal context.
    def amount(cents):
        return f"{cents // 100}.{cents % 100:02d}"
    totals = {name: amount(sum(share["cents"] for share in shares if share["destination"] == name))
              for name in ("remaining", "disposed", "production")}
    return {"amount_byn": amount(total_cents.numerator), "basis": data.basis, "rounding": data.rounding,
            "shares": [{key: value for key, value in share.items() if key not in {"cents", "remainder"}}
                       | {"amount_byn": amount(share["cents"])} for share in shares],
            "totals_byn": totals, "status": "arithmetic_preview", "posted": False,
            "source_movements_verified": False, "final_cost_certified": False}
