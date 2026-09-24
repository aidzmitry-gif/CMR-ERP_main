"""The FSZN ceiling preview is monthly, source-scoped and never payroll posting."""
from decimal import Decimal
from uuid import uuid4

from modules.accounting.models import AccessGrant, Organization
from modules.accounting.payroll_candidate import (
    _monthly_fszn_cap_rows,
    _monthly_fszn_minimum_rows,
)
from tests.accounting.test_payroll_organization_review import file_command


def test_monthly_ceiling_aggregates_segments_for_the_same_employee():
    rows, exceeded = _monthly_fszn_cap_rows([
        (41, 101, Decimal("10000.00")),
        (41, 102, Decimal("6000.00")),
        (42, 103, Decimal("2000.00")),
    ], Decimal("15000.00"))
    assert exceeded is True
    assert rows == [
        {"employee_id": 41, "review_ids": [101, 102],
         "listed_eligible_base_byn": "16000.00", "capped_listed_base_byn": "15000.00"},
        {"employee_id": 42, "review_ids": [103],
         "listed_eligible_base_byn": "2000.00", "capped_listed_base_byn": "2000.00"},
    ]
    next_month, exceeded_next_month = _monthly_fszn_cap_rows(
        [(41, 104, Decimal("3000.00"))], Decimal("15000.00"),
    )
    assert exceeded_next_month is False
    assert next_month[0]["capped_listed_base_byn"] == "3000.00"


def test_article_9_reference_aggregates_time_and_listed_rates_without_repricing():
    segments = [{
        "employee_id": 41, "binding_id": 7, "review_id": review_id,
        "worked_hours": Decimal("40.00"), "norm_hours": Decimal("160.00"),
        "rates": (("FSZN-EMPLOYER", Decimal("20")),),
        "listed_contributions": Decimal("30.00"),
    } for review_id in (101, 102)]
    segments.append({**segments[0], "employee_id": 42, "binding_id": 8,
                     "review_id": 103})
    rows, issues = _monthly_fszn_minimum_rows(
        segments, {7: {"condition": "applies", "full_month_norm_hours": "160.00"},
                   8: {"condition": "excluded_civil_contract"}}, Decimal("2000.00"),
    )
    assert rows[0] == {
        "employee_id": 41, "review_ids": [101, 102], "chief_condition": "applies",
        "status": "comparison", "worked_hours": "80.00", "full_month_norm_hours": "160.00",
        "time_adjusted_minimum_base_byn": "1000.00",
        "listed_fszn_components_byn": "60.00",
        "minimum_of_listed_components_byn": "200.00",
        "indicative_shortfall_byn": "140.00",
    }
    assert rows[1]["status"] == "chief_recorded_exception"
    assert "minimum_of_listed_components_byn" not in rows[1]
    assert issues == {"fszn_minimum_recalculation_required"}


def test_article_9_reference_refuses_unreviewed_and_inconsistent_employee_inputs():
    segment = {
        "employee_id": 41, "binding_id": 7, "review_id": 101,
        "worked_hours": Decimal("80.00"), "norm_hours": Decimal("160.00"),
        "rates": (("FSZN", Decimal("20")),),
        "listed_contributions": Decimal("100.00"),
    }
    unreviewed, issues = _monthly_fszn_minimum_rows(
        [segment], {}, Decimal("1000.00"),
    )
    assert unreviewed[0]["status"] == "unreviewed"
    assert issues == {"fszn_minimum_condition_unreviewed"}
    ambiguous, issues = _monthly_fszn_minimum_rows(
        [segment, {**segment, "review_id": 102, "norm_hours": Decimal("168.00")}],
        {7: {"condition": "applies", "full_month_norm_hours": "160.00"}}, Decimal("1000.00"),
    )
    assert ambiguous[0]["status"] == "ambiguous_inputs"
    assert issues == {"fszn_minimum_inputs_ambiguous"}
    payment_exception, issues = _monthly_fszn_minimum_rows(
        [segment], {7: {"condition": "excluded_employee_fault_norm"}}, Decimal("1000.00"),
    )
    assert payment_exception[0]["status"] == "requires_payment_breakdown"
    assert "minimum_of_listed_components_byn" not in payment_exception[0]
    assert issues == {"fszn_minimum_payment_exception_needs_breakdown"}

    missing, issues = _monthly_fszn_minimum_rows(
        [segment], {7: {"condition": "applies"}}, Decimal("1000.00"),
    )
    assert missing[0]["status"] == "missing_full_norm"
    assert "time_adjusted_minimum_base_byn" not in missing[0]
    assert issues == {"fszn_minimum_full_norm_missing"}


def test_article_9_part_time_individual_norm_is_not_the_full_month_denominator():
    segment = {
        "employee_id": 41, "binding_id": 7, "review_id": 101,
        "worked_hours": Decimal("80.00"), "norm_hours": Decimal("80.00"),
        "rates": (("FSZN", Decimal("20")),),
        "listed_contributions": Decimal("50.00"),
    }
    rows, issues = _monthly_fszn_minimum_rows(
        [segment], {7: {"condition": "applies", "full_month_norm_hours": "160.00"}},
        Decimal("2000.00"),
    )
    assert rows[0]["time_adjusted_minimum_base_byn"] == "1000.00"
    assert rows[0]["full_month_norm_hours"] == "160.00"
    assert issues == {"fszn_minimum_recalculation_required"}


async def test_fszn_reference_wage_review_requires_preceding_month_and_current_file(
        client, db, book, tmp_path, monkeypatch):
    root = tmp_path / "payroll"
    root.mkdir()
    monkeypatch.setenv("AIOS_PAYROLL_DATA_DIR", str(root.resolve()))
    org_id = book[0]
    prefix = f"/accounting/organizations/{org_id}"
    file = file_command(month="2026-09", reference="synthetic-august-wage-dossier")
    uploaded = await client.post(prefix + "/payroll-evidence-files", json=file)
    assert uploaded.status_code == 200, uploaded.text
    source = uploaded.json()
    command = {
        "request_key": str(uuid4()), "source_file_id": source["file_id"],
        "source_document": source["reference"],
        "facts": [{
            "code": "period_fszn_rules_and_limits", "decision": "applicable",
            "finding": "Synthetic chief review of the monthly FSZN reference",
            "source_locator": "page 1, national average wage",
            "reference_wage_month": "2026-08", "reference_wage_byn": "3135.90",
            "reference_wage_published_on": "2026-09-24",
            "reference_wage_url": (
                "https://www.belstat.gov.by/upload-belstat/upload-belstat-pdf/"
                "oficial_statistika/2026/zarplata-2608.pdf"),
        }],
        "evidence": "Synthetic chief identified the wage month and stored PDF",
        "supersedes_id": None,
    }
    endpoint = prefix + "/periods/2026-09/payroll-organization-reviews"
    wrong_month = {**command, "facts": [{**command["facts"][0],
                                          "reference_wage_month": "2026-07"}]}
    assert (await client.post(endpoint, json=wrong_month)).status_code == 422
    wrong_host = {**command, "facts": [{**command["facts"][0],
                                         "reference_wage_url": "https://example.com/wage.pdf"}]}
    assert (await client.post(endpoint, json=wrong_host)).status_code == 422
    unnormalized = {**command, "facts": [{**command["facts"][0],
                                           "reference_wage_byn": "3135.9"}]}
    assert (await client.post(endpoint, json=unnormalized)).status_code == 422
    other = Organization(name="Other synthetic wage employer", unp="654654654")
    db.add(other)
    await db.flush()
    db.add(AccessGrant(organization_id=other.id, subject="tester", role="chief"))
    await db.commit()
    assert (await client.post(
        f"/accounting/organizations/{other.id}/periods/2026-09/payroll-organization-reviews",
        json=command,
    )).status_code == 422
    first = await client.post(endpoint, json=command)
    assert first.status_code == 200, first.text
    assert first.json()["facts"][0]["reference_wage_byn"] == "3135.90"
    assert (await client.post(endpoint, json=command)).json() == first.json()
    current = await client.get(endpoint + "/current")
    assert current.status_code == 200
    candidate = await client.get(prefix + "/periods/2026-09/payroll-own-candidate")
    assert candidate.status_code == 200, candidate.text
    reference = candidate.json()["applicability"]["organization"]["fszn_reference_wage"]
    assert reference["wage_month"] == "2026-08"
    assert reference["wage_byn"] == "3135.90"
    assert reference["source_file_id"] == source["file_id"]
    assert candidate.json()["posting_available"] is False
    assert candidate.json()["statutory_payroll_certified"] is False

    stored = root / str(org_id) / (file["request_key"].replace("-", "") + ".pdf")
    original = stored.read_bytes()
    stored.write_bytes(b"%PDF-1.7\nchanged source\n")
    assert (await client.get(endpoint + "/current")).status_code == 409
    assert (await client.get(prefix + "/periods/2026-09/payroll-own-candidate")).status_code == 409
    stored.write_bytes(original)
    assert (await client.get(endpoint + "/current")).status_code == 200
