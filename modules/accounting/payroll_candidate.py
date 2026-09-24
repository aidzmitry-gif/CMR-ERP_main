"""Content-addressed monthly payroll candidate; never a posting instruction."""
from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from fastapi import HTTPException
from sqlalchemy import select

from modules.accounting.models import PayrollWorkpaperReview
from modules.accounting.payroll_applicability import assess as assess_applicability
from modules.accounting.payroll_applicability_review import current_for as current_applicability
from modules.accounting.payroll_calculation import (
    effective_percentage_rate,
    month_bounds,
    verified_policy,
)
from modules.accounting.payroll_evidence_files import file_for
from modules.accounting.payroll_organization_review import (
    current_for as current_organization_review,
)
from modules.accounting.payroll_population import (
    state as population_state,
)
from modules.accounting.payroll_population import (
    verify_for_close as verify_population,
)
from modules.accounting.payroll_rule_set import (
    current as current_rule_set,
)
from modules.accounting.payroll_rule_set import (
    result as rule_set_result,
)
from modules.accounting.payroll_workpaper_review import (
    AMOUNT_FIELDS,
    _amount,
    _review_amounts,
    monthly_arithmetic_summary,
)
from modules.accounting.payroll_workpaper_review import (
    result as review_result,
)
from modules.accounting.service import AccountingError, lock_organization

FSZN_MINIMUM_EXCEPTIONS = {
    "excluded_civil_contract", "excluded_correctional_or_ltp",
    "excluded_public_religious",
}


def _digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    ).encode()).hexdigest()


def _rate(value: object) -> Decimal:
    if not isinstance(value, str):
        raise HTTPException(409, "Payroll FSZN rate requires reconciliation")
    try:
        rate = Decimal(value)
    except InvalidOperation as exc:
        raise HTTPException(409, "Payroll FSZN rate requires reconciliation") from exc
    if not rate.is_finite() or rate < 0:
        raise HTTPException(409, "Payroll FSZN rate requires reconciliation")
    return rate


def _monthly_fszn_cap_rows(segments: list[tuple[int, int, Decimal]],
                           cap: Decimal) -> tuple[list[dict], bool]:
    """Compare listed monthly bases per employee; never calculate contributions."""
    by_employee: dict[int, dict] = {}
    for employee_id, review_id, base in segments:
        item = by_employee.setdefault(employee_id, {
            "employee_id": employee_id, "review_ids": [],
            "listed_eligible_base_byn": Decimal("0"),
        })
        item["review_ids"].append(review_id)
        item["listed_eligible_base_byn"] += base
    exceeded = False
    rows = []
    for employee in sorted(by_employee.values(), key=lambda item: item["employee_id"]):
        listed_base = employee["listed_eligible_base_byn"]
        exceeded |= listed_base > cap
        rows.append({
            "employee_id": employee["employee_id"],
            "review_ids": employee["review_ids"],
            "listed_eligible_base_byn": format(listed_base, ".2f"),
            "capped_listed_base_byn": format(min(listed_base, cap), ".2f"),
        })
    return rows, exceeded


def _monthly_fszn_minimum_rows(segments: list[dict],
                               conditions: dict[int, dict],
                               minimum_wage: Decimal) -> tuple[list[dict], set[str]]:
    """Compare listed FSZN components with Article 9's time-adjusted reference.

    Decisions, payment scope and configured rates are supplied by the chief;
    these rows are not a statutory contribution calculation.
    """
    grouped: dict[int, list[dict]] = {}
    for segment in segments:
        grouped.setdefault(segment["employee_id"], []).append(segment)
    rows: list[dict] = []
    issues: set[str] = set()
    for employee_id, parts in sorted(grouped.items()):
        binding_ids = {part["binding_id"] for part in parts}
        row = {"employee_id": employee_id,
               "review_ids": [part["review_id"] for part in parts]}
        if len(binding_ids) != 1:
            row["status"] = "ambiguous_multiple_bindings"
            issues.add("fszn_minimum_inputs_ambiguous")
        else:
            reviewed = conditions.get(next(iter(binding_ids)), {})
            condition = reviewed.get("condition")
            row["chief_condition"] = condition
            if condition not in FSZN_MINIMUM_EXCEPTIONS | {"applies", "excluded_employee_fault_norm"}:
                row["status"] = "unreviewed"
                issues.add("fszn_minimum_condition_unreviewed")
            elif condition == "excluded_employee_fault_norm":
                # Article 9 names a payment for work below the norm, not a
                # blanket exemption for every payment to this employee.
                row["status"] = "requires_payment_breakdown"
                issues.add("fszn_minimum_payment_exception_needs_breakdown")
            elif condition in FSZN_MINIMUM_EXCEPTIONS:
                row["status"] = "chief_recorded_exception"
            else:
                norms = {part["norm_hours"] for part in parts}
                rate_sets = {part["rates"] for part in parts}
                worked = sum((part["worked_hours"] for part in parts), Decimal("0"))
                full_norm_text = reviewed.get("full_month_norm_hours")
                if full_norm_text is None:
                    row["status"] = "missing_full_norm"
                    issues.add("fszn_minimum_full_norm_missing")
                    rows.append(row)
                    continue
                try:
                    full_norm = Decimal(full_norm_text)
                except (InvalidOperation, TypeError) as exc:
                    raise HTTPException(409, "FSZN full-month norm requires reconciliation") from exc
                if (len(norms) != 1 or len(rate_sets) != 1
                        or not norms or next(iter(norms)) <= 0
                        or full_norm <= 0 or worked <= 0 or worked > full_norm):
                    row["status"] = "ambiguous_inputs"
                    issues.add("fszn_minimum_inputs_ambiguous")
                else:
                    floor = (minimum_wage * worked / full_norm).quantize(
                        Decimal("0.01"), rounding=ROUND_HALF_UP,
                    )
                    rates = next(iter(rate_sets))
                    reference = sum(((floor * rate / Decimal("100")).quantize(
                        Decimal("0.01"), rounding=ROUND_HALF_UP,
                    ) for _, rate in rates), Decimal("0"))
                    listed = sum((part["listed_contributions"] for part in parts),
                                 Decimal("0"))
                    shortfall = max(Decimal("0"), reference - listed)
                    row.update({
                        "status": "comparison", "worked_hours": format(worked, ".2f"),
                        "full_month_norm_hours": format(full_norm, ".2f"),
                        "time_adjusted_minimum_base_byn": format(floor, ".2f"),
                        "listed_fszn_components_byn": format(listed, ".2f"),
                        "minimum_of_listed_components_byn": format(reference, ".2f"),
                        "indicative_shortfall_byn": format(shortfall, ".2f"),
                    })
                    if shortfall:
                        issues.add("fszn_minimum_recalculation_required")
        rows.append(row)
    return rows, issues


async def preview(session, org_id: int, month: str) -> dict:
    """Build a repeatable partial candidate from current, chief-attested reviews."""
    await lock_organization(session, org_id)
    first, last = month_bounds(month)
    summary = await monthly_arithmetic_summary(session, org_id, month)
    population = await population_state(session, org_id, month)
    blockers: list[str] = []
    if not summary["selected_segment_count"]:
        blockers.append("no_reviewed_segments")
    if summary["source_fact_unattested_review_ids"]:
        blockers.append("source_facts_not_attested")
    if not summary["known_binding_coverage"]["known_binding_coverage_complete"]:
        blockers.append("known_binding_coverage_incomplete")
    if not population["matches_current_bindings"]:
        blockers.append("population_review_missing_or_stale")
        population_review = None
    else:
        population_review = (await verify_population(session, org_id, month))["review"]

    ruleset = await current_rule_set(session, org_id, first)
    rule = rule_set_result(ruleset) if ruleset else None
    if rule is None:
        blockers.append("rule_set_missing")
    else:
        try:
            await verified_policy(session, org_id, first, last, rule["policy_id"])
        except AccountingError:
            blockers.append("accounting_policy_changed_or_unverified")
        if rule["source_file_id"] is None:
            blockers.append("rule_source_file_missing")
        else:
            source = await file_for(session, org_id, rule["source_file_id"], kind="payroll_policy")
            if source.reference != rule["source_reference"] or source.sha256 != rule["source_digest"]:
                raise HTTPException(409, "Payroll candidate rule source differs from configured file")

    selected = [segment for binding in summary["bindings"] for segment in binding["segments"]]
    ids = [segment["review_id"] for segment in selected]
    rows = (await session.scalars(select(PayrollWorkpaperReview).where(
        PayrollWorkpaperReview.organization_id == org_id,
        PayrollWorkpaperReview.month == month,
        PayrollWorkpaperReview.id.in_(ids),
    ))).all() if ids else []
    by_id = {row.id: row for row in rows}
    if len(by_id) != len(ids):
        raise HTTPException(409, "Payroll candidate selected review requires reconciliation")

    totals = {field: Decimal("0") for field in AMOUNT_FIELDS}
    binding_rows: dict[int, dict] = {}
    fszn_segments: list[tuple[int, int, Decimal]] = []
    fszn_minimum_segments: list[dict] = []
    included = []
    stale_rule = False
    fszn_base_conflict = False
    fszn_rate_codes = {rate["code"] for rate in (rule["rate_rules"] if rule else [])
                       if rate.get("obligation_code") == "period_fszn_rules_and_limits"}
    for binding in summary["bindings"]:
        for segment in binding["segments"]:
            row = by_id[segment["review_id"]]
            receipt = review_result(row)
            if (row.snapshot_digest != segment["snapshot_digest"]
                    or row.basis_digest != segment["basis_digest"]
                    or row.employment_binding_id != binding["employment_binding_id"]):
                raise HTTPException(409, "Payroll candidate selected review differs from summary")
            if not receipt["source_facts_attested_by_chief"]:
                continue
            basis = receipt["snapshot"].get("basis")
            if not isinstance(basis, dict):
                raise HTTPException(409, "Payroll candidate source basis requires reconciliation")
            if rule is None or (basis.get("rule_set_id") != rule["rule_set_id"]
                                or basis.get("rule_set_digest") != rule["digest"]):
                stale_rule = True
            for component in basis["components"]:
                try:
                    _, current_rate = await effective_percentage_rate(
                        session, org_id, component["requirement_id"],
                        date.fromisoformat(segment["work_to"]),
                    )
                except AccountingError:
                    stale_rule = True
                    continue
                if current_rate["digest"] != component["requirement_digest"]:
                    stale_rule = True
            amounts = _review_amounts(row)
            if fszn_rate_codes:
                components = [component for component in basis["components"]
                              if component["rate_code"] in fszn_rate_codes]
                component_bases = {_amount(component.get("base_byn"))
                                   for component in components}
                if len(components) != len(fszn_rate_codes) or len(component_bases) != 1:
                    fszn_base_conflict = True
                else:
                    employee_id = basis.get("employee_id")
                    if type(employee_id) is not int or employee_id <= 0:
                        raise HTTPException(409, "Payroll candidate employee identity requires reconciliation")
                    fszn_segments.append((employee_id, row.id, component_bases.pop()))
                    fszn_minimum_segments.append({
                        "employee_id": employee_id,
                        "binding_id": binding["employment_binding_id"],
                        "review_id": row.id,
                        "worked_hours": _amount(basis["worked_hours"]),
                        "norm_hours": _amount(basis["month_norm_hours"]),
                        "rates": tuple(sorted((component["rate_code"],
                                                _rate(component["rate_value"]))
                                               for component in components)),
                        "listed_contributions": sum(
                            (_amount(component["amount_byn"]) for component in components),
                            Decimal("0"),
                        ),
                    })
            item = binding_rows.setdefault(binding["employment_binding_id"], {
                "employment_binding_id": binding["employment_binding_id"],
                "review_ids": [],
                "totals": {field: Decimal("0") for field in AMOUNT_FIELDS},
            })
            item["review_ids"].append(row.id)
            included.append({"review_id": row.id, "snapshot_digest": row.snapshot_digest})
            for field in AMOUNT_FIELDS:
                item["totals"][field] += amounts[field]
                totals[field] += amounts[field]
    if stale_rule:
        blockers.append("rule_version_changed")
    applicability_reviews = await current_applicability(
        session, org_id, month, population["known_binding_ids"],
    )
    organization_review = await current_organization_review(session, org_id, month)
    applicability = assess_applicability(
        month, population["known_binding_ids"], applicability_reviews,
        organization_review,
    )
    decisions = applicability["organization"]["rule_decisions"]
    rate_obligations = [{
        "rate_code": rate_rule["code"],
        "obligation_code": rate_rule.get("obligation_code"),
        "chief_decision": decisions.get(rate_rule.get("obligation_code")),
    } for rate_rule in (rule["rate_rules"] if rule else [])]
    applicability["rate_obligations"] = rate_obligations
    if any(row["obligation_code"] is None for row in rate_obligations):
        blockers.append("payroll_rate_obligation_unmapped")
    if any(row["obligation_code"] is not None
           and row["chief_decision"] in (None, "unresolved")
           for row in rate_obligations):
        blockers.append("payroll_rate_obligation_unreviewed")
    if any(row["chief_decision"] == "not_applicable" for row in rate_obligations):
        blockers.append("payroll_rate_conflicts_with_organization_review")
    fszn_cap_preview = None
    fszn_minimum_preview = None
    reference_wage = (organization_review or {}).get("fszn_reference_wage")
    if fszn_base_conflict:
        blockers.append("fszn_segment_bases_disagree")
    if (fszn_rate_codes and not stale_rule
            and decisions.get("period_fszn_rules_and_limits") == "applicable"):
        if reference_wage is None:
            blockers.append("fszn_reference_wage_missing")
        elif not fszn_base_conflict:
            cap = _amount(reference_wage["wage_byn"]) * 5
            rows, cap_exceeded = _monthly_fszn_cap_rows(fszn_segments, cap)
            if cap_exceeded:
                blockers.append("fszn_components_need_monthly_recalculation")
            fszn_cap_preview = {
                "scope": "attested_erp_segments_only",
                "month": month,
                "multiplier": 5,
                "reference_wage": reference_wage,
                "ceiling_byn": format(cap, ".2f"),
                "employees": rows,
                "all_selected_segments_attested": not summary["source_fact_unattested_review_ids"],
                "statutory_base_certified": False,
                "contributions_recalculated": False,
            }
        minimum_wage = (organization_review or {}).get("fszn_minimum_wage")
        if minimum_wage is None:
            blockers.append("fszn_minimum_wage_missing")
        elif not fszn_base_conflict:
            minimum_rows, minimum_issues = _monthly_fszn_minimum_rows(
                fszn_minimum_segments,
                {binding_id: {"condition": review.get("fszn_minimum_condition"),
                              "full_month_norm_hours": review.get("fszn_minimum_full_month_norm_hours")}
                 for binding_id, review in applicability_reviews.items()},
                _amount(minimum_wage["wage_byn"]),
            )
            blockers.extend(sorted(minimum_issues))
            fszn_minimum_preview = {
                "scope": "attested_erp_segments_and_listed_rates_only",
                "month": month, "minimum_wage": minimum_wage,
                "employees": minimum_rows,
                "all_selected_segments_attested": not summary["source_fact_unattested_review_ids"],
                "statutory_minimum_certified": False,
                "contributions_recalculated": False,
            }
    # A configured percentage list is not proof that every legally applicable
    # deduction, exemption, cap, benefit or employee-specific fact was covered.
    blockers.append("statutory_rule_completeness_unverified")
    formatted = {field: format(value, ".2f") for field, value in totals.items()}
    bindings = [{**item, "totals": {field: format(value, ".2f")
                                    for field, value in item["totals"].items()}}
                for item in binding_rows.values()]
    source_basis = {
        "organization_id": org_id, "month": month,
        "selection_digest": summary["selection_digest"],
        "coverage_digest": summary["coverage_digest"],
        "population_review_id": population_review["review_id"] if population_review else None,
        "population_review_digest": population_review["digest"] if population_review else None,
        "rule_set_id": rule["rule_set_id"] if rule else None,
        "rule_set_digest": rule["digest"] if rule else None,
        "included_reviews": included,
        "applicability": applicability,
        "fszn_monthly_cap_preview": fszn_cap_preview,
        "fszn_minimum_preview": fszn_minimum_preview,
        "blockers": blockers,
        "totals": formatted,
    }
    return {
        "status": "provisional_payroll_candidate_only",
        "organization_id": org_id, "month": month,
        "candidate_digest": _digest(source_basis), "source_basis": source_basis,
        "included_segment_count": len(included),
        "selected_segment_count": summary["selected_segment_count"],
        "unattested_review_ids": summary["source_fact_unattested_review_ids"],
        "bindings": bindings, "totals": formatted, "blockers": blockers,
        "applicability": applicability,
        "fszn_monthly_cap_preview": fszn_cap_preview,
        "fszn_minimum_preview": fszn_minimum_preview,
        "arithmetic_scope_complete": not any(code not in {
            "statutory_rule_completeness_unverified",
            "payroll_rate_obligation_unmapped",
            "payroll_rate_obligation_unreviewed",
            "payroll_rate_conflicts_with_organization_review",
        } for code in blockers),
        "population_source_facts_verified_by_software": False,
        "statutory_payroll_certified": False,
        "posting_available": False,
        "payment_available": False,
    }
