"""A multi-component workpaper must keep every source explicit and stay read-only."""
import base64
import hashlib
from uuid import uuid4

import pytest_asyncio
from sqlalchemy import func, select

from modules.accounting import statutory_requirements
from modules.accounting.models import AccessGrant, Entry, Organization
from modules.hr.models import Employee
from tests.accounting.test_payroll_calculation import rate_input


@pytest_asyncio.fixture
async def workpaper_sources(client, db, book):
    employee = Employee(full_name="Synthetic Employee", department="repair",
                        position="technician")
    db.add(employee)
    await db.flush()
    employee_id = employee.id
    await db.commit()
    binding = await client.post(f"/accounting/organizations/{book[0]}/payroll-employments", json={
        "request_key": str(uuid4()),
        "employee_id": employee_id,
        "contract_ref": "contract-2026-7",
        "effective_from": "2026-01-01",
        "state": "active",
        "source_document": "signed-contract-2026-7",
        "evidence": "Synthetic accountant supplied contract evidence",
    })
    assert binding.status_code == 200, binding.text
    deduction = await statutory_requirements.create(db, book[0], rate_input(
        request_key=str(uuid4()), code="SYNTHETIC-EMPLOYEE-DEDUCTION", value="10",
    ), "tester")
    contribution = await statutory_requirements.create(db, book[0], rate_input(
        request_key=str(uuid4()), code="SYNTHETIC-EMPLOYER-CONTRIBUTION", value="20",
    ), "tester")
    await db.commit()
    ruleset = await client.post(f"/accounting/organizations/{book[0]}/payroll-rule-sets", json={
        "request_key": str(uuid4()),
        "policy_id": book[1],
        "effective_from": "2026-01-01",
        "gross_method": "monthly_salary_by_hours",
        "rounding": "half_up_cent",
        "rate_rules": [
            {"code": "SYNTHETIC-EMPLOYEE-DEDUCTION", "role": "employee_deduction",
             "base_mode": "gross", "classification_evidence": "Synthetic documented deduction classification"},
            {"code": "SYNTHETIC-EMPLOYER-CONTRIBUTION", "role": "employer_contribution",
             "base_mode": "gross_less_adjustment",
             "classification_evidence": "Synthetic documented contribution classification"},
        ],
        "source_reference": "synthetic-reviewed-payroll-policy",
        "source_digest": "c" * 64,
        "evidence": "Synthetic accountant supplied gross method and rounding policy evidence",
    })
    assert ruleset.status_code == 200, ruleset.text
    return binding.json(), deduction, contribution, ruleset.json()


def command(policy_id, binding_id, deduction_id, contribution_id, ruleset_id, **changes):
    payload = {
        "policy_id": policy_id,
        "rule_set_id": ruleset_id,
        "employment_binding_id": binding_id,
        "work_from": "2026-10-01",
        "work_to": "2026-10-31",
        "monthly_salary_byn": "1500.00",
        "contract_document": "signed-contract-2026-7",
        "contract_digest": "a" * 64,
        "contract_amount_evidence": "Synthetic contract salary line and date evidence",
        "timesheet_document": "reviewed-timesheet-2026-10-7",
        "timesheet_digest": "b" * 64,
        "timesheet_evidence": "Synthetic reviewed October hours evidence",
        "month_norm_hours": "160.00",
        "worked_hours": "80.00",
        "components": [
            {
                "requirement_id": deduction_id,
                "adjustment_byn": "0.00",
            },
            {
                "requirement_id": contribution_id,
                "adjustment_byn": "100.00",
                "adjustment_document": "synthetic-adjustment-source",
                "adjustment_evidence": "Synthetic explicit rate base adjustment evidence",
            },
        ],
    }
    payload.update(changes)
    return payload


async def test_workpaper_calculates_listed_components_without_posting(
        client, db, book, workpaper_sources):
    binding, deduction, contribution, ruleset = workpaper_sources
    before = await db.scalar(select(func.count(Entry.id)))
    url = f"/accounting/organizations/{book[0]}/periods/2026-10/payroll-workpaper-preview"
    payload = command(book[1], binding["binding_id"],
                      deduction["requirement_id"], contribution["requirement_id"],
                      ruleset["rule_set_id"])
    response = await client.post(url, json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["gross_byn"] == "750.00"
    assert body["listed_employee_deductions_byn"] == "75.00"
    assert body["after_listed_deductions_byn"] == "675.00"
    assert body["listed_employer_contributions_byn"] == "130.00"
    assert body["cost_including_listed_contributions_byn"] == "880.00"
    assert body["basis"]["employment_binding_digest"] == binding["digest"]
    assert body["basis"]["rule_set_digest"] == ruleset["digest"]
    assert body["basis"]["components"][1]["base_byn"] == "650.00"
    assert len(body["basis_digest"]) == 64
    assert body["status"] == "arithmetic_workpaper_only"
    assert body["posting_available"] is False
    assert body["statutory_payroll_certified"] is False
    assert body["contract_and_timesheet_hashes_verified"] is False
    assert body["rule_set_configured"] is True
    assert "unlisted_components" in body["not_calculated"]
    assert response.headers["cache-control"] == "private, no-store"
    assert await db.scalar(select(func.count(Entry.id))) == before

    rounded = command(book[1], binding["binding_id"],
                      deduction["requirement_id"], contribution["requirement_id"],
                      ruleset["rule_set_id"],
                      monthly_salary_byn="1000.00", month_norm_hours="3.00",
                      worked_hours="1.00")
    second = await client.post(url, json=rounded)
    assert second.status_code == 200, second.text
    assert second.json()["gross_byn"] == "333.33"
    assert second.json()["listed_employee_deductions_byn"] == "33.33"
    assert second.json()["basis_digest"] != body["basis_digest"]


async def test_workpaper_rejects_unproven_shape_and_partial_period_binding(
        client, db, book, workpaper_sources):
    binding, deduction, contribution, ruleset = workpaper_sources
    url = f"/accounting/organizations/{book[0]}/periods/2026-10/payroll-workpaper-preview"
    args = (book[1], binding["binding_id"], deduction["requirement_id"],
            contribution["requirement_id"], ruleset["rule_set_id"])
    for changes in (
        {"monthly_salary_byn": 1500.00},
        {"worked_hours": "161.00"},
        {"contract_digest": "missing"},
        {"contract_document": "unrelated-contract"},
        {"work_to": "2026-11-01"},
    ):
        response = await client.post(url, json=command(*args, **changes))
        assert response.status_code == 422, (changes, response.text)

    wrong_adjustment = command(*args)
    wrong_adjustment["components"][0]["adjustment_byn"] = "1.00"
    assert (await client.post(url, json=wrong_adjustment)).status_code == 422
    missing_evidence = command(*args)
    del missing_evidence["components"][1]["adjustment_evidence"]
    assert (await client.post(url, json=missing_evidence)).status_code == 422

    incomplete = command(*args)
    incomplete["components"].pop()
    missing_rate = await client.post(url, json=incomplete)
    assert missing_rate.status_code == 422
    assert "every configured payroll rate" in missing_rate.text

    newer_rule_set = await client.post(
        f"/accounting/organizations/{book[0]}/payroll-rule-sets",
        json={
            "request_key": str(uuid4()),
            "policy_id": book[1],
            "effective_from": "2026-01-01",
            "gross_method": "monthly_salary_by_hours",
            "rounding": "half_up_cent",
            "rate_rules": ruleset["rate_rules"],
            "source_reference": "synthetic-corrected-policy",
            "source_digest": "d" * 64,
            "evidence": "Synthetic reviewed replacement policy evidence",
        },
    )
    assert newer_rule_set.status_code == 200, newer_rule_set.text
    stale = await client.post(url, json=command(*args))
    assert stale.status_code == 422
    assert "current payroll rule set" in stale.text
    args = (*args[:-1], newer_rule_set.json()["rule_set_id"])

    ended = await client.post(f"/accounting/organizations/{book[0]}/payroll-employments", json={
        "request_key": str(uuid4()),
        "employee_id": binding["employee_id"],
        "contract_ref": binding["contract_ref"],
        "effective_from": "2026-10-15",
        "state": "ended",
        "source_document": "synthetic-contract-end-7",
        "evidence": "Synthetic accountant supplied termination evidence",
    })
    assert ended.status_code == 200, ended.text
    blocked = await client.post(url, json=command(*args))
    assert blocked.status_code == 422
    assert "ended or superseded" in blocked.text


async def test_workpaper_rejects_foreign_rate_and_reader(
        client, db, book, workpaper_sources):
    binding, deduction, contribution, ruleset = workpaper_sources
    other = Organization(name="Other synthetic employer", unp="777777777")
    db.add(other)
    await db.flush()
    foreign_rate = await statutory_requirements.create(db, other.id, rate_input(
        request_key=str(uuid4()), code="FOREIGN-RATE", value="10",
    ), "tester")
    await db.commit()
    url = f"/accounting/organizations/{book[0]}/periods/2026-10/payroll-workpaper-preview"
    response = await client.post(url, json=command(
        book[1], binding["binding_id"], foreign_rate["requirement_id"],
        contribution["requirement_id"], ruleset["rule_set_id"],
    ))
    assert response.status_code == 422
    assert "not effective for this organization" in response.text

    grant = await db.scalar(select(AccessGrant).where(
        AccessGrant.organization_id == book[0], AccessGrant.subject == "tester",
    ))
    grant.role = "reader"
    await db.commit()
    denied = await client.post(url, json=command(
        book[1], binding["binding_id"], deduction["requirement_id"],
        contribution["requirement_id"], ruleset["rule_set_id"],
    ))
    assert denied.status_code == 403


async def test_workpaper_verifies_stored_contract_and_timesheet_bytes(
        client, db, book, workpaper_sources, tmp_path, monkeypatch):
    binding, deduction, contribution, ruleset = workpaper_sources
    root = tmp_path / "payroll"
    root.mkdir()
    monkeypatch.setenv("AIOS_PAYROLL_DATA_DIR", str(root.resolve()))
    url = f"/accounting/organizations/{book[0]}/payroll-evidence-files"

    async def upload(kind, reference, month=None):
        raw = (f"%PDF-1.7\nsynthetic {kind} evidence\n").encode()
        response = await client.post(url, json={
            "request_key": str(uuid4()), "kind": kind,
            "employment_binding_id": binding["binding_id"], "month": month,
            "reference": reference, "filename": f"{kind}.pdf",
            "data_url": "data:application/pdf;base64," + base64.b64encode(raw).decode(),
            "evidence": "Synthetic source for byte verification test",
        })
        assert response.status_code == 200, response.text
        return response.json(), raw

    contract, _ = await upload("employment_contract", "signed-contract-2026-7")
    timesheet, _ = await upload("timesheet", "reviewed-timesheet-2026-10-7", "2026-10")
    preview_url = f"/accounting/organizations/{book[0]}/periods/2026-10/payroll-workpaper-preview"
    args = (book[1], binding["binding_id"], deduction["requirement_id"],
            contribution["requirement_id"], ruleset["rule_set_id"])
    fields = {
        "contract_file_id": contract["file_id"], "contract_digest": contract["sha256"],
        "timesheet_file_id": timesheet["file_id"], "timesheet_digest": timesheet["sha256"],
    }
    accepted = await client.post(preview_url, json=command(*args, **fields))
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["contract_and_timesheet_hashes_verified"] is True
    assert accepted.json()["basis"]["contract_file_id"] == contract["file_id"]

    wrong_claim = await client.post(preview_url, json=command(*args, **{
        **fields, "timesheet_digest": hashlib.sha256(b"different").hexdigest(),
    }))
    assert wrong_claim.status_code == 422
    assert "differ from stored" in wrong_claim.text
    partial = await client.post(preview_url, json=command(*args, **{
        **fields, "timesheet_file_id": None,
    }))
    assert partial.status_code == 422

    # Corrupt both possible files: whichever is selected must fail byte verification.
    for path in (root / str(book[0])).glob("*.pdf"):
        path.write_bytes(b"%PDF-1.7\ncorrupted")
    tampered = await client.post(preview_url, json=command(*args, **fields))
    assert tampered.status_code == 409
