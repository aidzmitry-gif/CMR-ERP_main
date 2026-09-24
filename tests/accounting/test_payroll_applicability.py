from modules.accounting.payroll_applicability import assess


def test_another_year_does_not_inherit_2026_tax_sources_or_assumed_rates():
    assessment = assess("2027-01", [8, 3, 8])
    assert assessment["reference_scope"] == "no_period_source_checked"
    assert assessment["references"] == []
    assert "period_income_tax_sources_unverified" in assessment["organization_gap_codes"]
    assert [row["employment_binding_id"] for row in assessment["bindings"]] == [3, 8]
    assert assessment["statutory_completeness_verified"] is False
    assert "rate" not in assessment
