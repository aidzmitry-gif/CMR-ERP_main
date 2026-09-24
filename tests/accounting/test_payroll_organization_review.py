"""Employer payroll-rule facts stay sourced and provisional across revisions."""
import base64
from uuid import uuid4

from sqlalchemy import select

from modules.accounting.models import (
    AccessGrant,
    Organization,
    PayrollOrganizationReview,
    Period,
)


def file_command(month="2026-10", reference="synthetic-employer-rule-dossier"):
    return {
        "request_key": str(uuid4()), "kind": "payroll_organization_rule",
        "employment_binding_id": None, "month": month,
        "reference": reference, "filename": "employer-rules.pdf",
        "data_url": "data:application/pdf;base64," + base64.b64encode(
            b"%PDF-1.7\nsynthetic employer facts, not a legal source\n").decode(),
        "evidence": "Synthetic chief prepared employer rule evidence",
    }


def review_command(source_id: int, reference: str, *, decision="unresolved"):
    return {
        "request_key": str(uuid4()), "source_file_id": source_id,
        "source_document": reference,
        "facts": [{
            "code": "period_work_injury_insurance_tariff",
            "decision": decision,
            "finding": "Organization tariff requires a signed period notice",
            "source_locator": "page 1, section 2",
        }],
        "evidence": "Synthetic chief checked the cited employer rule source",
        "supersedes_id": None,
    }


async def test_organization_review_changes_candidate_without_certifying_payroll(
        client, db, book, tmp_path, monkeypatch):
    root = tmp_path / "payroll"
    root.mkdir()
    monkeypatch.setenv("AIOS_PAYROLL_DATA_DIR", str(root.resolve()))
    org_id = book[0]
    prefix = f"/accounting/organizations/{org_id}"
    candidate_url = prefix + "/periods/2026-10/payroll-own-candidate"
    before = (await client.get(candidate_url)).json()
    assert before["applicability"]["organization"]["review_id"] is None

    source = file_command()
    uploaded = await client.post(prefix + "/payroll-evidence-files", json=source)
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["employment_binding_id"] is None
    review_url = prefix + "/periods/2026-10/payroll-organization-reviews"
    command = review_command(uploaded.json()["file_id"], source["reference"])
    first = await client.post(review_url, json=command)
    assert first.status_code == 200, first.text
    receipt = first.json()
    assert receipt["revision"] == 1
    assert receipt["posting_available"] is False
    assert receipt["statutory_payroll_certified"] is False
    assert receipt["fact_findings_verified_by_software"] is False
    assert (await client.post(review_url, json=command)).json() == receipt
    assert (await client.get(prefix + "/payroll-organization-reviews/by-request/"
                             + command["request_key"])).json() == receipt
    current = await client.get(review_url + "/current")
    assert current.status_code == 200
    assert current.json()["source_file_bytes_verified_now"] is True
    candidate = (await client.get(candidate_url)).json()
    assert candidate["candidate_digest"] != before["candidate_digest"]
    org_review = candidate["applicability"]["organization"]
    assert org_review["review_id"] == receipt["review_id"]
    assert org_review["reviewed_rule_codes"] == []
    assert "period_work_injury_insurance_tariff" in org_review["unresolved_rule_codes"]
    assert "period_work_injury_insurance_tariff" in candidate["applicability"]["organization_gap_codes"]
    assert "statutory_rule_completeness_unverified" in candidate["blockers"]
    assert candidate["posting_available"] is False

    revised_command = {**command, "request_key": str(uuid4()),
                       "supersedes_id": receipt["review_id"],
                       "facts": [{**command["facts"][0], "decision": "applicable",
                                  "finding": "Signed tariff notice reviewed for this employer"}]}
    revised = await client.post(review_url, json=revised_command)
    assert revised.status_code == 200, revised.text
    assert revised.json()["revision"] == 2
    after = (await client.get(candidate_url)).json()
    assert after["candidate_digest"] != candidate["candidate_digest"]
    assert after["applicability"]["organization"]["reviewed_rule_codes"] == [
        "period_work_injury_insurance_tariff",
    ]
    assert after["applicability"]["statutory_completeness_verified"] is False
    assert await db.scalar(select(PayrollOrganizationReview.id).where(
        PayrollOrganizationReview.id == receipt["review_id"],
    )) == receipt["review_id"]

    stored = root / str(org_id) / (source["request_key"].replace("-", "") + ".pdf")
    original = stored.read_bytes()
    stored.write_bytes(b"%PDF-1.7\ntampered\n")
    assert (await client.get(candidate_url)).status_code == 409
    assert (await client.get(review_url + "/current")).status_code == 409
    stored.write_bytes(original)
    assert (await client.get(candidate_url)).status_code == 200


async def test_organization_review_scopes_permissions_period_and_replay(
        client, db, book, tmp_path, monkeypatch):
    root = tmp_path / "payroll"
    root.mkdir()
    monkeypatch.setenv("AIOS_PAYROLL_DATA_DIR", str(root.resolve()))
    org_id = book[0]
    prefix = f"/accounting/organizations/{org_id}"
    source = file_command()
    uploaded = await client.post(prefix + "/payroll-evidence-files", json=source)
    assert uploaded.status_code == 200
    command = review_command(uploaded.json()["file_id"], source["reference"])
    review_url = prefix + "/periods/2026-10/payroll-organization-reviews"
    grant = await db.scalar(select(AccessGrant).where(
        AccessGrant.organization_id == org_id, AccessGrant.subject == "tester",
    ))
    grant.role = "accountant"
    await db.commit()
    assert (await client.post(review_url, json=command)).status_code == 403
    assert (await client.post(prefix + "/payroll-evidence-files",
                              json=file_command())).status_code == 403
    grant.role = "chief"
    await db.commit()

    other = Organization(name="Other synthetic employer", unp="321321321")
    db.add(other)
    await db.commit()
    db.add(AccessGrant(organization_id=other.id, subject="tester", role="chief"))
    await db.commit()
    assert (await client.post(
        f"/accounting/organizations/{other.id}/periods/2026-10/payroll-organization-reviews",
        json=command,
    )).status_code == 422
    assert (await client.post(prefix + "/periods/2026-11/payroll-organization-reviews",
                              json=command)).status_code == 422
    first = await client.post(review_url, json=command)
    assert first.status_code == 200, first.text
    assert (await client.post(review_url, json={**command,
                                               "evidence": "Changed same-key request"})).status_code == 409
    assert (await client.post(review_url, json={**command, "request_key": str(uuid4()),
                                               "supersedes_id": 987654})).status_code == 422
    bad = {**command, "request_key": str(uuid4()),
           "supersedes_id": first.json()["review_id"],
           "facts": [{**command["facts"][0], "decision": "unknown"}]}
    assert (await client.post(review_url, json=bad)).status_code == 422

    db.add(Period(organization_id=org_id, month="2026-11", closed=True))
    await db.commit()
    assert (await client.post(review_url, json=command)).json() == first.json()
    assert (await client.post(review_url, json={**command, "request_key": str(uuid4()),
                                               "supersedes_id": first.json()["review_id"]}
                              )).status_code == 422
    assert (await client.post(prefix + "/payroll-evidence-files",
                              json=file_command())).status_code == 422
