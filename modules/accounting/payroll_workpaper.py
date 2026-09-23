"""Organization-bound gross-to-net arithmetic workpaper without statutory claims.

No pay rule, rate, contract amount, time fact or deduction is supplied by a
default.  This is a read-only calculation over explicitly identified sources;
the accountant must still verify their applicability before any payroll run.
"""
from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal, localcontext
from typing import Annotated

from pydantic import BeforeValidator, Field, model_validator
from starlette.concurrency import run_in_threadpool

from modules.accounting.payroll_calculation import (
    _digest,
    active_employment,
    effective_percentage_rate,
    month_bounds,
    verified_policy,
)
from modules.accounting.payroll_evidence_files import file_for as evidence_file_for
from modules.accounting.payroll_evidence_files import timesheet_preflight
from modules.accounting.payroll_evidence_files import verify_bytes as verify_evidence_bytes
from modules.accounting.payroll_rule_set import current as current_rule_set
from modules.accounting.payroll_rule_set import result as rule_set_result
from modules.accounting.schemas import Input, Money, exact
from modules.accounting.service import AccountingError
from modules.accounting.timesheet_preflight import UnsupportedWorkbook, row_numeric_hours

Hours = Annotated[Decimal, BeforeValidator(exact), Field(ge=0, max_digits=5, decimal_places=2)]
CENT = Decimal("0.01")
MAX_MONEY = Decimal("999999999999999999.99")


class PayrollWorkpaperComponent(Input):
    requirement_id: int = Field(gt=0, strict=True)
    adjustment_byn: Money
    adjustment_document: str | None = Field(default=None, min_length=1, max_length=160)
    adjustment_evidence: str | None = Field(default=None, min_length=10, max_length=2000)
    adjustment_file_id: int | None = Field(default=None, gt=0, strict=True)

class PayrollWorkpaperInput(Input):
    policy_id: int = Field(gt=0, strict=True)
    rule_set_id: int = Field(gt=0, strict=True)
    employment_binding_id: int = Field(gt=0, strict=True)
    work_from: date
    work_to: date
    monthly_salary_byn: Money = Field(gt=0)
    contract_document: str = Field(min_length=1, max_length=160)
    contract_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    contract_file_id: int | None = Field(default=None, gt=0, strict=True)
    contract_amount_evidence: str = Field(min_length=10, max_length=2000)
    timesheet_document: str = Field(min_length=1, max_length=160)
    timesheet_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    timesheet_file_id: int | None = Field(default=None, gt=0, strict=True)
    timesheet_row: int | None = Field(default=None, ge=11, strict=True)
    timesheet_evidence: str = Field(min_length=10, max_length=2000)
    work_schedule_document: str | None = Field(default=None, min_length=1, max_length=160)
    work_schedule_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    work_schedule_file_id: int | None = Field(default=None, gt=0, strict=True)
    norm_hours_evidence: str | None = Field(default=None, min_length=10, max_length=2000)
    month_norm_hours: Hours = Field(gt=0, le=744)
    worked_hours: Hours = Field(le=744)
    components: list[PayrollWorkpaperComponent] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def check_hours_and_rates(self):
        if self.work_from > self.work_to:
            raise ValueError("Work period is reversed")
        if self.worked_hours > self.month_norm_hours:
            raise ValueError("Worked hours exceed monthly norm; overtime needs its own rule")
        schedule = (self.work_schedule_document, self.work_schedule_digest,
                    self.work_schedule_file_id, self.norm_hours_evidence)
        if any(value is not None for value in schedule) and not all(
                value is not None for value in schedule):
            raise ValueError("Work schedule file, digest, reference and norm evidence must be supplied together")
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
    ruleset = await current_rule_set(session, org_id, first)
    if ruleset is None or ruleset.id != data.rule_set_id or ruleset.policy_id != policy.id:
        raise AccountingError("Select the current payroll rule set for this organization and month")
    configured_rules = rule_set_result(ruleset)
    rule_source_file_id = configured_rules["source_file_id"]
    rule_source_bytes_verified = rule_source_file_id is not None
    if rule_source_bytes_verified:
        rule_source_file = await evidence_file_for(
            session, org_id, rule_source_file_id, kind="payroll_policy",
        )
        if (rule_source_file.reference != ruleset.source_reference
                or rule_source_file.sha256 != ruleset.source_digest):
            raise AccountingError("Payroll rule source differs from stored source file")
    by_code = {rule["code"]: rule for rule in configured_rules["rate_rules"]}
    configured_versions = ruleset.snapshot.get("rates_at_configuration")
    if (not isinstance(configured_versions, list)
            or len(configured_versions) != len(by_code)
            or any(not isinstance(version, dict)
                   or version.get("code") not in by_code
                   or type(version.get("requirement_id")) is not int
                   or not isinstance(version.get("requirement_digest"), str)
                   for version in configured_versions)):
        raise AccountingError("Payroll rule set rate versions require reconciliation")
    versions_by_code = {version["code"]: version for version in configured_versions}
    if len(versions_by_code) != len(by_code):
        raise AccountingError("Payroll rule set rate versions require reconciliation")
    if len(data.components) != len(by_code):
        raise AccountingError("Workpaper must include every configured payroll rate once")
    binding, employment = await active_employment(
        session, org_id, data.employment_binding_id, data.work_from,
    )
    await active_employment(session, org_id, binding.id, data.work_to)
    if data.contract_document != binding.source_document:
        raise AccountingError("Salary document must match the current employment binding")
    if (data.contract_file_id is None) != (data.timesheet_file_id is None):
        raise AccountingError("Contract and timesheet source files must be selected together")
    source_files_verified = data.contract_file_id is not None
    timesheet_row_check = None
    schedule_bytes_verified = False
    if source_files_verified:
        contract_file = await evidence_file_for(
            session, org_id, data.contract_file_id, kind="employment_contract",
            employment_binding_id=binding.id,
        )
        timesheet_file = await evidence_file_for(
            session, org_id, data.timesheet_file_id, kind="timesheet",
            employment_binding_id=binding.id, month=month,
        )
        if (contract_file.reference != data.contract_document
                or contract_file.sha256 != data.contract_digest
                or timesheet_file.reference != data.timesheet_document
                or timesheet_file.sha256 != data.timesheet_digest):
            raise AccountingError("Workpaper source claims differ from stored source files")
        if timesheet_file.content_type == (
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"):
            preflight = await run_in_threadpool(timesheet_preflight, timesheet_file)
            if preflight["status"] == "structure_checked":
                if data.timesheet_row is None:
                    raise AccountingError("Select the employee row of the XLSX timesheet")
                raw = await run_in_threadpool(verify_evidence_bytes, timesheet_file)
                try:
                    timesheet_row_check = await run_in_threadpool(
                        row_numeric_hours, raw, month, data.timesheet_row,
                        data.work_from, data.work_to)
                except UnsupportedWorkbook as exc:
                    raise AccountingError("XLSX row or work interval failed source verification") from exc
                if (timesheet_row_check["source_sha256"] != timesheet_file.sha256
                        or Decimal(timesheet_row_check["numeric_hours"]) != data.worked_hours):
                    raise AccountingError("Worked hours differ from the selected XLSX row and interval")
            elif data.timesheet_row is not None:
                raise AccountingError("Employee row requires a structurally valid XLSX source")
        elif data.timesheet_row is not None:
            raise AccountingError("Timesheet row applies only to an XLSX source")
    elif data.timesheet_row is not None:
        raise AccountingError("Timesheet row requires a stored XLSX source")

    if data.work_schedule_file_id is not None:
        schedule_file = await evidence_file_for(
            session, org_id, data.work_schedule_file_id, kind="work_schedule",
            employment_binding_id=binding.id, month=month,
        )
        if (schedule_file.reference != data.work_schedule_document
                or schedule_file.sha256 != data.work_schedule_digest):
            raise AccountingError("Monthly work schedule differs from stored source file")
        schedule_bytes_verified = True

    with localcontext() as context:
        context.prec = 64
        gross = (data.monthly_salary_byn * data.worked_hours / data.month_norm_hours).quantize(
            CENT, rounding=ROUND_HALF_UP,
        )
        component_rows = []
        deductions = Decimal("0")
        employer_contributions = Decimal("0")
        used_codes = set()
        for component in data.components:
            rate, rate_info = await effective_percentage_rate(
                session, org_id, component.requirement_id, data.work_to,
            )
            rule = by_code.get(rate.code)
            if rule is None or rate.code in used_codes:
                raise AccountingError("Workpaper rate differs from the current payroll rule set")
            used_codes.add(rate.code)
            configured_version = versions_by_code[rate.code]
            if (rate.id != configured_version["requirement_id"]
                    or rate_info["digest"] != configured_version["requirement_digest"]):
                raise AccountingError(
                    "Payroll rate version changed since payroll rule set configuration")
            if rule["base_mode"] == "gross":
                if (component.adjustment_byn != 0 or component.adjustment_document
                        or component.adjustment_evidence or component.adjustment_file_id):
                    raise AccountingError("Gross rate base cannot contain an adjustment")
            elif not component.adjustment_document or not component.adjustment_evidence:
                raise AccountingError("Adjusted rate base requires document and evidence")
            adjustment_file_digest = None
            if component.adjustment_file_id is not None:
                adjustment_file = await evidence_file_for(
                    session, org_id, component.adjustment_file_id, kind="base_adjustment",
                    employment_binding_id=binding.id, month=month,
                )
                if adjustment_file.reference != component.adjustment_document:
                    raise AccountingError("Rate-base adjustment differs from stored source file")
                adjustment_file_digest = adjustment_file.sha256
            if component.adjustment_byn > gross:
                raise AccountingError("Rate-base adjustment exceeds calculated gross pay")
            base = gross - component.adjustment_byn
            amount = (base * rate.rate_value / Decimal("100")).quantize(
                CENT, rounding=ROUND_HALF_UP,
            )
            if amount > MAX_MONEY:
                raise AccountingError("Payroll component exceeds the accounting money range")
            if rule["role"] == "employee_deduction":
                deductions += amount
            else:
                employer_contributions += amount
            component_rows.append({
                "requirement_id": rate.id,
                "requirement_digest": rate_info["digest"],
                "rate_code": rate.code,
                "rate_value": rate_info["rate_value"],
                "rate_basis": rate.rate_basis,
                "role": rule["role"],
                "classification_evidence": rule["classification_evidence"],
                "base_mode": rule["base_mode"],
                "adjustment_byn": format(component.adjustment_byn, ".2f"),
                "adjustment_document": component.adjustment_document,
                "adjustment_evidence": component.adjustment_evidence,
                "adjustment_file_id": component.adjustment_file_id,
                "adjustment_file_digest": adjustment_file_digest,
                "base_byn": format(base, ".2f"),
                "amount_byn": format(amount, ".2f"),
            })
        if used_codes != set(by_code):
            raise AccountingError("Workpaper omits a configured payroll rate")
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
        "rule_set_id": ruleset.id,
        "rule_set_digest": ruleset.digest,
        "rule_set_source_reference": ruleset.source_reference,
        "rule_set_source_digest": ruleset.source_digest,
        "rule_set_source_file_id": rule_source_file_id,
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
        "contract_file_id": data.contract_file_id,
        "contract_amount_evidence": data.contract_amount_evidence,
        "timesheet_document": data.timesheet_document,
        "timesheet_digest": data.timesheet_digest,
        "timesheet_file_id": data.timesheet_file_id,
        "timesheet_row": data.timesheet_row,
        "timesheet_numeric_hours_verified": timesheet_row_check is not None,
        "timesheet_uninterpreted_code_days": (
            timesheet_row_check["uninterpreted_code_days"] if timesheet_row_check else None),
        "timesheet_evidence": data.timesheet_evidence,
        "work_schedule_document": data.work_schedule_document,
        "work_schedule_digest": data.work_schedule_digest,
        "work_schedule_file_id": data.work_schedule_file_id,
        "schedule_file_bytes_verified": schedule_bytes_verified,
        "norm_hours_evidence": data.norm_hours_evidence,
        "month_norm_hours": format(data.month_norm_hours, ".2f"),
        "worked_hours": format(data.worked_hours, ".2f"),
        "method": ruleset.gross_method,
        "gross_formula": "round_half_up(monthly_salary_byn * worked_hours / month_norm_hours, 2)",
        "method_evidence": ruleset.evidence,
        "rounding": ruleset.rounding,
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
        "contract_and_timesheet_hashes_verified": source_files_verified,
        "timesheet_numeric_hours_verified": timesheet_row_check is not None,
        "schedule_file_bytes_verified": schedule_bytes_verified,
        "rule_set_configured": True,
        "rule_source_file_bytes_verified": rule_source_bytes_verified,
        "method_and_rate_classification_verified": False,
        "needs_accountant_review": True,
        "not_calculated": [
            "document_authenticity", "rule_source_authenticity", "method_applicability",
            "rate_eligibility",
            "exemptions", "caps", "benefits", "unlisted_components",
            "period_aggregation", "statutory_forms", "timesheet_row_identity",
            "timesheet_code_meanings",
        ],
    }
