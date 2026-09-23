"""Organization-bound gross-to-net arithmetic workpaper without statutory claims.

No pay rule, rate, contract amount, time fact or deduction is supplied by a
default.  This is a read-only calculation over explicitly identified sources;
the accountant must still verify their applicability before any payroll run.
"""
from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal, localcontext
from typing import Annotated, Literal

from pydantic import BeforeValidator, Field, model_validator

from modules.accounting.payroll_calculation import (
    _digest,
    active_employment,
    effective_percentage_rate,
    month_bounds,
    verified_policy,
)
from modules.accounting.schemas import Input, Money, exact
from modules.accounting.service import AccountingError

Hours = Annotated[Decimal, BeforeValidator(exact), Field(ge=0, max_digits=5, decimal_places=2)]
CENT = Decimal("0.01")
MAX_MONEY = Decimal("999999999999999999.99")


class PayrollWorkpaperComponent(Input):
    requirement_id: int = Field(gt=0, strict=True)
    role: Literal["employee_deduction", "employer_contribution"]
    classification_document: str = Field(min_length=1, max_length=160)
    classification_evidence: str = Field(min_length=10, max_length=2000)
    base_mode: Literal["gross", "gross_less_adjustment"]
    adjustment_byn: Money
    adjustment_document: str | None = Field(default=None, min_length=1, max_length=160)
    adjustment_evidence: str | None = Field(default=None, min_length=10, max_length=2000)

    @model_validator(mode="after")
    def check_adjustment(self):
        if self.base_mode == "gross":
            if self.adjustment_byn != 0 or self.adjustment_document or self.adjustment_evidence:
                raise ValueError("Gross rate base cannot contain an adjustment")
        elif not self.adjustment_document or not self.adjustment_evidence:
            raise ValueError("Adjusted rate base requires document and evidence")
        return self


class PayrollWorkpaperInput(Input):
    policy_id: int = Field(gt=0, strict=True)
    employment_binding_id: int = Field(gt=0, strict=True)
    work_from: date
    work_to: date
    monthly_salary_byn: Money = Field(gt=0)
    contract_document: str = Field(min_length=1, max_length=160)
    contract_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    contract_amount_evidence: str = Field(min_length=10, max_length=2000)
    timesheet_document: str = Field(min_length=1, max_length=160)
    timesheet_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    timesheet_evidence: str = Field(min_length=10, max_length=2000)
    month_norm_hours: Hours = Field(gt=0, le=744)
    worked_hours: Hours = Field(le=744)
    method: Literal["monthly_salary_by_hours"]
    method_evidence: str = Field(min_length=10, max_length=2000)
    rounding: Literal["half_up_cent"]
    rounding_evidence: str = Field(min_length=10, max_length=2000)
    components: list[PayrollWorkpaperComponent] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def check_hours_and_rates(self):
        if self.work_from > self.work_to:
            raise ValueError("Work period is reversed")
        if self.worked_hours > self.month_norm_hours:
            raise ValueError("Worked hours exceed monthly norm; overtime needs its own rule")
        identities = [component.requirement_id for component in self.components]
        if len(identities) != len(set(identities)):
            raise ValueError("Rate requirement cannot appear twice in one workpaper")
        return self


async def preview_workpaper(session, org_id: int, month: str,
                            data: PayrollWorkpaperInput) -> dict:
    first, last = month_bounds(month)
    if not first <= data.work_from <= data.work_to <= last:
        raise AccountingError("Work period must belong to the selected month")
    policy = await verified_policy(session, org_id, first, last, data.policy_id)
    binding, employment = await active_employment(
        session, org_id, data.employment_binding_id, data.work_from,
    )
    await active_employment(session, org_id, binding.id, data.work_to)
    if data.contract_document != binding.source_document:
        raise AccountingError("Salary document must match the current employment binding")

    with localcontext() as context:
        context.prec = 64
        gross = (data.monthly_salary_byn * data.worked_hours / data.month_norm_hours).quantize(
            CENT, rounding=ROUND_HALF_UP,
        )
        component_rows = []
        deductions = Decimal("0")
        employer_contributions = Decimal("0")
        for component in data.components:
            rate, rate_info = await effective_percentage_rate(
                session, org_id, component.requirement_id, data.work_to,
            )
            if component.adjustment_byn > gross:
                raise AccountingError("Rate-base adjustment exceeds calculated gross pay")
            base = gross - component.adjustment_byn
            amount = (base * rate.rate_value / Decimal("100")).quantize(
                CENT, rounding=ROUND_HALF_UP,
            )
            if amount > MAX_MONEY:
                raise AccountingError("Payroll component exceeds the accounting money range")
            if component.role == "employee_deduction":
                deductions += amount
            else:
                employer_contributions += amount
            component_rows.append({
                "requirement_id": rate.id,
                "requirement_digest": rate_info["digest"],
                "rate_code": rate.code,
                "rate_value": rate_info["rate_value"],
                "rate_basis": rate.rate_basis,
                "role": component.role,
                "classification_document": component.classification_document,
                "classification_evidence": component.classification_evidence,
                "base_mode": component.base_mode,
                "adjustment_byn": format(component.adjustment_byn, ".2f"),
                "adjustment_document": component.adjustment_document,
                "adjustment_evidence": component.adjustment_evidence,
                "base_byn": format(base, ".2f"),
                "amount_byn": format(amount, ".2f"),
            })
        if deductions > gross:
            raise AccountingError("Employee deductions exceed calculated gross pay")
        net = gross - deductions
        employer_cost = gross + employer_contributions
        if employer_cost > MAX_MONEY:
            raise AccountingError("Employer cost exceeds the accounting money range")

    basis = {
        "organization_id": org_id,
        "month": month,
        "policy_id": policy.id,
        "policy_reference": policy.reference,
        "employee_id": binding.employee_id,
        "employee_name": employment["employee_name"],
        "department": employment["department"],
        "contract_ref": binding.contract_ref,
        "employment_binding_id": binding.id,
        "employment_binding_digest": binding.digest,
        "work_from": data.work_from.isoformat(),
        "work_to": data.work_to.isoformat(),
        "monthly_salary_byn": format(data.monthly_salary_byn, ".2f"),
        "contract_document": data.contract_document,
        "contract_digest": data.contract_digest,
        "contract_amount_evidence": data.contract_amount_evidence,
        "timesheet_document": data.timesheet_document,
        "timesheet_digest": data.timesheet_digest,
        "timesheet_evidence": data.timesheet_evidence,
        "month_norm_hours": format(data.month_norm_hours, ".2f"),
        "worked_hours": format(data.worked_hours, ".2f"),
        "method": data.method,
        "gross_formula": "round_half_up(monthly_salary_byn * worked_hours / month_norm_hours, 2)",
        "method_evidence": data.method_evidence,
        "rounding": data.rounding,
        "rounding_evidence": data.rounding_evidence,
        "gross_byn": format(gross, ".2f"),
        "components": component_rows,
    }
    return {
        "status": "arithmetic_workpaper_only",
        "basis": basis,
        "basis_digest": _digest(basis),
        "gross_byn": format(gross, ".2f"),
        "listed_employee_deductions_byn": format(deductions, ".2f"),
        "after_listed_deductions_byn": format(net, ".2f"),
        "listed_employer_contributions_byn": format(employer_contributions, ".2f"),
        "cost_including_listed_contributions_byn": format(employer_cost, ".2f"),
        "posting_available": False,
        "statutory_payroll_certified": False,
        "contract_and_timesheet_hashes_verified": False,
        "method_and_rate_classification_verified": False,
        "needs_accountant_review": True,
        "not_calculated": [
            "document_authenticity", "method_applicability", "rate_eligibility",
            "exemptions", "caps", "benefits", "unlisted_components",
            "period_aggregation", "statutory_forms",
        ],
    }
