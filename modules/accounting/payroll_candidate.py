"""Content-addressed monthly payroll candidate; never a posting instruction."""
from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal

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
    _review_amounts,
    monthly_arithmetic_summary,
)
from modules.accounting.payroll_workpaper_review import (
    result as review_result,
)
from modules.accounting.service import AccountingError, lock_organization


def _digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    ).encode()).hexdigest()


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
    included = []
    stale_rule = False
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
