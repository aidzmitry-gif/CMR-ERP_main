"""Source-bound arithmetic preview for one payroll percentage component.

This is a building block for own payroll calculation, not a statutory payroll
result.  The caller supplies the verified base and its evidence; exemptions,
caps, eligibility and aggregation are not inferred here.  No ledger write occurs.
"""
from __future__ import annotations

import hashlib
import json
from calendar import monthrange
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, localcontext
from typing import Literal

from pydantic import Field
from sqlalchemy import select

from modules.accounting.models import Policy, StatutoryRequirement
from modules.accounting.schemas import Input, Money
from modules.accounting.service import AccountingError
from modules.accounting.statutory_requirements import result as requirement_result

_CENT = Decimal("0.01")
_MAX_MONEY = Decimal("999999999999999999.99")


class PayrollComponentPreviewInput(Input):
    policy_id: int = Field(gt=0, strict=True)
    calculation_date: date
    employee: str = Field(min_length=1, max_length=200)
    department: str = Field(min_length=1, max_length=200)
    requirement_id: int = Field(gt=0, strict=True)
    base_byn: Money
    base_document: str = Field(min_length=1, max_length=160)
    base_evidence: str = Field(min_length=10, max_length=2000)
    rounding: Literal["half_up_cent"]
    rounding_evidence: str = Field(min_length=10, max_length=2000)


def _digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    ).encode()).hexdigest()


async def preview_component(session, org_id: int, month: str,
                            data: PayrollComponentPreviewInput) -> dict:
    try:
        first = date.fromisoformat(month + "-01")
    except ValueError as exc:
        raise AccountingError("Month must be YYYY-MM") from exc
    if (first.strftime("%Y-%m") != month
            or data.calculation_date < first
            or data.calculation_date > first.replace(day=monthrange(first.year, first.month)[1])):
        raise AccountingError("Calculation date must belong to the selected period")
    last = first.replace(day=monthrange(first.year, first.month)[1])

    policy = await session.scalar(select(Policy).where(
        Policy.organization_id == org_id,
        Policy.effective_from <= last,
    ).order_by(Policy.effective_from.desc()))
    if (policy is None or policy.id != data.policy_id or policy.effective_from > first
            or not policy.normative_verified):
        raise AccountingError("Select a verified accounting policy applicable for the whole month")

    rate = await session.scalar(select(StatutoryRequirement).where(
        StatutoryRequirement.id == data.requirement_id,
        StatutoryRequirement.organization_id == org_id,
        StatutoryRequirement.kind == "rate",
        StatutoryRequirement.effective_from <= data.calculation_date,
    ))
    if rate is None:
        raise AccountingError("The selected rate is not effective for this organization and period")
    latest = await session.scalar(select(StatutoryRequirement.id).where(
        StatutoryRequirement.organization_id == org_id,
        StatutoryRequirement.kind == "rate",
        StatutoryRequirement.code == rate.code,
        StatutoryRequirement.effective_from <= data.calculation_date,
    ).order_by(
        StatutoryRequirement.effective_from.desc(),
        StatutoryRequirement.revision.desc(),
    ).limit(1))
    if latest != rate.id:
        raise AccountingError("The selected rate was superseded for this period")
    verified_rate = requirement_result(rate)
    if (rate.rate_unit != "percent" or rate.rate_value is None
            or not rate.rate_basis or not rate.source_reference or not rate.evidence):
        raise AccountingError("The selected percentage rate has incomplete provenance")

    with localcontext() as context:
        context.prec = 64
        amount = (data.base_byn * rate.rate_value / Decimal("100")).quantize(
            _CENT, rounding=ROUND_HALF_UP,
        )
    if amount > _MAX_MONEY:
        raise AccountingError("Calculated amount exceeds the accounting money range")
    basis = {
        "organization_id": org_id,
        "month": month,
        "policy_id": policy.id,
        "employee": data.employee,
        "department": data.department,
        "calculation_date": data.calculation_date.isoformat(),
        "base_byn": format(data.base_byn, ".2f"),
        "base_document": data.base_document,
        "base_evidence": data.base_evidence,
        "requirement_id": rate.id,
        "requirement_digest": verified_rate["digest"],
        "rate_value": verified_rate["rate_value"],
        "rate_unit": rate.rate_unit,
        "rate_basis": rate.rate_basis,
        "rounding": data.rounding,
        "rounding_evidence": data.rounding_evidence,
    }
    return {
        "status": "arithmetic_preview_only",
        "basis": basis,
        "basis_digest": _digest(basis),
        "amount_byn": format(amount, ".2f"),
        "posting_available": False,
        "statutory_payroll_certified": False,
        "needs_accountant_review": True,
        "not_calculated": ["base_eligibility", "exemptions", "caps", "period_aggregation"],
    }
