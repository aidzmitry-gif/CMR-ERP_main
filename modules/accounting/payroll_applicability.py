"""Source-scoped payroll applicability gaps, not a legal payroll decision.

Only the listed 2026 income-tax topics were checked against MNS pages.  An
employee's actual treatment and the insurance rules still require evidence.
"""
from __future__ import annotations

_MNS_2026_SOURCES = [
    {
        "topic": "income_tax_rate_categories",
        "url": "https://nalog.gov.by/news/34207/",
    },
    {
        "topic": "standard_deductions_and_main_workplace",
        "url": "https://nalog.gov.by/individuals/income_taxation/tax_deductions/9332/",
    },
    {
        "topic": "deduction_categories",
        "url": "https://nalog.gov.by/individuals/income_taxation/tax_deductions/",
    },
]

_EMPLOYEE_FACT_CODES = [
    "income_kind_and_tax_agent_treatment",
    "year_to_date_taxable_income",
    "main_workplace_and_deduction_basis",
    "dependants_special_status_and_deduction_documents",
    "other_deduction_claims_and_documents",
    "insurance_applicability_and_base",
]

_ORGANIZATION_RULE_CODES = [
    "period_income_tax_withholding_rule",
    "period_fszn_rules_and_limits",
    "period_work_injury_insurance_tariff",
]


def assess(month: str, binding_ids: list[int]) -> dict:
    """List facts ERP does not record; never infer that a deduction is zero."""
    year = int(month[:4])
    organization_gaps = list(_ORGANIZATION_RULE_CODES)
    if year != 2026:
        organization_gaps.insert(0, "period_income_tax_sources_unverified")
    return {
        "status": "facts_and_rules_unverified",
        "population_scope": "known_erp_bindings_only",
        "reference_year": year,
        "reference_scope": "selected_mns_topics_only" if year == 2026 else "no_period_source_checked",
        "references": list(_MNS_2026_SOURCES) if year == 2026 else [],
        "organization_gap_codes": organization_gaps,
        "bindings": [
            {"employment_binding_id": binding_id,
             "unrecorded_fact_codes": list(_EMPLOYEE_FACT_CODES)}
            for binding_id in sorted(set(binding_ids))
        ],
        "statutory_completeness_verified": False,
    }
