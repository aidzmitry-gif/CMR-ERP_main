"""The FSZN ceiling preview is monthly, source-scoped and never payroll posting."""
from decimal import Decimal
from uuid import uuid4

from modules.accounting.models import AccessGrant, Organization
from modules.accounting.payroll_candidate import _monthly_fszn_cap_rows
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
