"""A chief's fact review is sourced, scoped and revisable without posting."""
import base64
from uuid import uuid4

from sqlalchemy import select

from modules.accounting.models import AccessGrant, Organization, PayrollApplicabilityReview, Period
from modules.hr.models import Employee


def source_command(binding_id: int, *, month="2026-10", reference="synthetic-fact-dossier"):
    return {
        "request_key": str(uuid4()), "kind": "payroll_applicability",
        "employment_binding_id": binding_id, "month": month,
        "reference": reference, "filename": "facts.pdf",
        "data_url": "data:application/pdf;base64," + base64.b64encode(
            b"%PDF-1.7\nsynthetic employee facts, not a legal source\n").decode(),
        "evidence": "Synthetic chief prepared an employee facts dossier",
    }


async def binding(client, db, org_id: int, name: str) -> int:
    employee = Employee(full_name=name, department="repair")
    db.add(employee)
    await db.commit()
    response = await client.post(f"/accounting/organizations/{org_id}/payroll-employments", json={
        "request_key": str(uuid4()), "employee_id": employee.id,
        "contract_ref": f"synthetic-{employee.id}", "effective_from": "2026-10-01",
        "state": "active", "source_document": f"synthetic-contract-{employee.id}",
        "evidence": "Synthetic employment source for applicability review",
    })
    assert response.status_code == 200, response.text
    return response.json()["binding_id"]


async def test_fact_review_is_append_only_and_candidate_checks_current_source(
        client, db, book, tmp_path, monkeypatch):
    root = tmp_path / "payroll"
    root.mkdir()
    monkeypatch.setenv("AIOS_PAYROLL_DATA_DIR", str(root.resolve()))
    org_id = book[0]
    binding_id = await binding(client, db, org_id, "Synthetic Employee")
    prefix = f"/accounting/organizations/{org_id}"
    file_command = source_command(binding_id)
    uploaded = await client.post(prefix + "/payroll-evidence-files", json=file_command)
    assert uploaded.status_code == 200, uploaded.text
    source_id = uploaded.json()["file_id"]
    url = prefix + "/periods/2026-10/payroll-applicability-reviews"
    command = {
        "request_key": str(uuid4()), "employment_binding_id": binding_id,
        "source_file_id": source_id, "source_document": file_command["reference"],
        "facts": [{
            "code": "main_workplace_and_deduction_basis",
            "finding": "Main workplace asserted in the source dossier",
            "source_locator": "page 1, section 2",
        }],
        "evidence": "Synthetic chief checked the cited source location",
    }
    first = await client.post(url, json=command)
    assert first.status_code == 200, first.text
    receipt = first.json()
    assert receipt["revision"] == 1
    assert receipt["fact_findings_verified_by_software"] is False
    assert receipt["posting_available"] is False
    assert (await client.post(url, json=command)).json() == receipt
    assert (await client.get(prefix + "/payroll-applicability-reviews/by-request/"
                             + command["request_key"])).json() == receipt
    assert await db.scalar(select(PayrollApplicabilityReview.id)) == receipt["review_id"]
    assert (await client.post(url, json={**command, "evidence": "Changed evidence on same key"})).status_code == 409

    current = await client.get(url + f"/{binding_id}")
    assert current.status_code == 200
    assert current.json()["source_file_bytes_verified_now"] is True
    candidate_url = prefix + "/periods/2026-10/payroll-own-candidate"
    candidate = (await client.get(candidate_url)).json()
    fact_row = candidate["applicability"]["bindings"][0]
    assert fact_row["review_id"] == receipt["review_id"]
    assert fact_row["reviewed_fact_codes"] == ["main_workplace_and_deduction_basis"]
    assert "main_workplace_and_deduction_basis" not in fact_row["unrecorded_fact_codes"]
    assert candidate["statutory_payroll_certified"] is False
    assert candidate["posting_available"] is False

    second_command = {
        **command, "request_key": str(uuid4()), "supersedes_id": receipt["review_id"],
        "facts": [{
            "code": "year_to_date_taxable_income",
            "finding": "Income data remains incomplete for this calendar year",
            "source_locator": "page 1, section 3",
        }],
    }
    second = await client.post(url, json=second_command)
    assert second.status_code == 200, second.text
    assert second.json()["revision"] == 2
    revised = (await client.get(candidate_url)).json()
    assert revised["candidate_digest"] != candidate["candidate_digest"]
    fact_row = revised["applicability"]["bindings"][0]
    assert fact_row["reviewed_fact_codes"] == ["year_to_date_taxable_income"]
    assert "main_workplace_and_deduction_basis" in fact_row["unrecorded_fact_codes"]
    assert (await client.get(prefix + "/payroll-applicability-reviews/by-request/"
                             + command["request_key"])).json() == receipt

    stored = root / str(org_id) / (file_command["request_key"].replace("-", "") + ".pdf")
    original = stored.read_bytes()
    stored.write_bytes(b"%PDF-1.7\ntampered\n")
    assert (await client.get(candidate_url)).status_code == 409
    assert (await client.get(url + f"/{binding_id}")).status_code == 409
    stored.write_bytes(original)
    assert (await client.get(candidate_url)).status_code == 200


async def test_fact_review_rejects_other_book_closed_period_and_non_chief(
        client, db, book, tmp_path, monkeypatch):
    root = tmp_path / "payroll"
    root.mkdir()
    monkeypatch.setenv("AIOS_PAYROLL_DATA_DIR", str(root.resolve()))
    org_id = book[0]
    binding_id = await binding(client, db, org_id, "First Employee")
    prefix = f"/accounting/organizations/{org_id}"
    file_command = source_command(binding_id)
    uploaded = await client.post(prefix + "/payroll-evidence-files", json=file_command)
    assert uploaded.status_code == 200, uploaded.text
    url = prefix + "/periods/2026-10/payroll-applicability-reviews"
    command = {
        "request_key": str(uuid4()), "employment_binding_id": binding_id,
        "source_file_id": uploaded.json()["file_id"],
        "source_document": file_command["reference"],
        "facts": [{"code": "insurance_applicability_and_base",
                   "finding": "Insurance treatment needs a separate legal review",
                   "source_locator": "page 1, section 4"}],
        "evidence": "Synthetic chief recorded a non-certified insurance fact",
    }
    grant = await db.scalar(select(AccessGrant).where(
        AccessGrant.organization_id == org_id, AccessGrant.subject == "tester",
    ))
    grant.role = "accountant"
    await db.commit()
    assert (await client.post(url, json=command)).status_code == 403
    grant.role = "chief"
    await db.commit()

    other = Organization(name="Other synthetic payroll book", unp="321321321")
    db.add(other)
    await db.commit()
    db.add(AccessGrant(organization_id=other.id, subject="tester", role="chief"))
    await db.commit()
    assert (await client.post(
        f"/accounting/organizations/{other.id}/periods/2026-10/payroll-applicability-reviews",
        json=command,
    )).status_code == 422
    accepted = await client.post(url, json=command)
    assert accepted.status_code == 200
    assert (await client.post(url, json={**command, "source_document": "wrong"})).status_code == 409
    assert (await client.post(url, json={**command, "request_key": str(uuid4()),
                                         "source_document": "wrong"})).status_code == 422
    db.add(Period(organization_id=org_id, month="2026-11", closed=True))
    await db.commit()
    assert (await client.post(url, json=command)).json() == accepted.json()
    assert (await client.post(url, json={**command, "request_key": str(uuid4()),
                                         "supersedes_id": accepted.json()["review_id"]})).status_code == 422
    assert (await client.post(prefix + "/payroll-evidence-files",
                              json=source_command(binding_id))).status_code == 422
