"""A multi-component workpaper must keep every source explicit and stay read-only."""
import base64
import hashlib
from datetime import date
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import func, select, update

from modules.accounting import payroll_evidence_files, statutory_requirements
from modules.accounting.models import (
    AccessGrant,
    Account,
    Entry,
    Line,
    Organization,
    PayrollWorkpaperReview,
    Period,
)
from modules.hr.models import Employee
from tests.accounting.test_payroll_calculation import rate_input
from tests.accounting.test_timesheet_preflight import make_timesheet


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
    access = await client.get(f"/accounting/organizations/{book[0]}/payroll-workpaper-access")
    assert access.status_code == 200
    assert access.json() == {
        "organization_id": book[0], "can_preview": True,
        "can_upload": True, "can_review": True,
    }
    assert access.headers["cache-control"] == "private, no-store"
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
    unbacked_review = await client.post(
        f"/accounting/organizations/{book[0]}/periods/2026-10/payroll-workpaper-reviews",
        json={**payload, "request_key": str(uuid4()),
              "basis_digest": body["basis_digest"],
              "reviewer_evidence": "Synthetic review without stored source files"},
    )
    assert unbacked_review.status_code == 422
    assert "requires stored contract" in unbacked_review.text

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


async def test_workpaper_requires_rule_set_review_after_rate_revision(
        client, db, book, workpaper_sources):
    binding, deduction, contribution, ruleset = workpaper_sources
    updated_rate = await statutory_requirements.create(db, book[0], rate_input(
        request_key=str(uuid4()), code="SYNTHETIC-EMPLOYEE-DEDUCTION",
        value="12", effective_from="2026-10-01",
    ), "tester")
    await db.commit()

    url = f"/accounting/organizations/{book[0]}/periods/2026-10/payroll-workpaper-preview"
    stale_rules = await client.post(url, json=command(
        book[1], binding["binding_id"], updated_rate["requirement_id"],
        contribution["requirement_id"], ruleset["rule_set_id"],
    ))
    assert stale_rules.status_code == 422
    assert "payroll rule set" in stale_rules.text

    september = await client.post(
        f"/accounting/organizations/{book[0]}/periods/2026-09/payroll-workpaper-preview",
        json=command(
            book[1], binding["binding_id"], deduction["requirement_id"],
            contribution["requirement_id"], ruleset["rule_set_id"],
            work_from="2026-09-01", work_to="2026-09-30",
            timesheet_document="reviewed-timesheet-2026-09-7",
        ),
    )
    assert september.status_code == 200, september.text
    assert september.json()["listed_employee_deductions_byn"] == "75.00"

    renewed = await client.post(
        f"/accounting/organizations/{book[0]}/payroll-rule-sets", json={
            "request_key": str(uuid4()),
            "policy_id": book[1],
            "effective_from": "2026-10-01",
            "gross_method": "monthly_salary_by_hours",
            "rounding": "half_up_cent",
            "rate_rules": ruleset["rate_rules"],
            "source_reference": "synthetic-reviewed-october-payroll-policy",
            "source_digest": "d" * 64,
            "evidence": "Synthetic chief review of the changed October rate version",
        },
    )
    assert renewed.status_code == 200, renewed.text
    current = await client.post(url, json=command(
        book[1], binding["binding_id"], updated_rate["requirement_id"],
        contribution["requirement_id"], renewed.json()["rule_set_id"],
    ))
    assert current.status_code == 200, current.text
    assert current.json()["listed_employee_deductions_byn"] == "90.00"
    assert current.json()["basis"]["rule_set_digest"] == renewed.json()["digest"]


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
    reader_access = (await client.get(
        f"/accounting/organizations/{book[0]}/payroll-workpaper-access",
    )).json()
    assert reader_access == {"organization_id": book[0], "can_preview": False,
                             "can_upload": False, "can_review": False}
    denied = await client.post(url, json=command(
        book[1], binding["binding_id"], deduction["requirement_id"],
        contribution["requirement_id"], ruleset["rule_set_id"],
    ))
    assert denied.status_code == 403


async def test_monthly_summary_exposes_unreviewed_known_employment(
        client, book, workpaper_sources):
    binding, _, _, _ = workpaper_sources
    url = f"/accounting/organizations/{book[0]}/periods/2026-10/payroll-arithmetic-summary"
    empty = await client.get(url)
    assert empty.status_code == 200, empty.text
    assert empty.json()["review_count"] == 0
    assert empty.json()["known_binding_coverage"] == {
        "active_binding_count": 1,
        "expected_intervals": [{"employment_binding_id": binding["binding_id"],
                                "work_from": "2026-10-01", "work_to": "2026-10-31"}],
        "known_binding_coverage_complete": False,
        "organization_payroll_population_verified": False,
        "issues": [{"kind": "unreviewed_interval",
                    "employment_binding_id": binding["binding_id"],
                    "work_from": "2026-10-01", "work_to": "2026-10-31"}],
    }
    assert empty.json()["coverage_verified"] is False

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
    shortened = (await client.get(url)).json()["known_binding_coverage"]
    assert shortened["expected_intervals"][0]["work_to"] == "2026-10-14"
    assert shortened["issues"][0]["work_from"] == "2026-10-01"
    assert shortened["issues"][0]["work_to"] == "2026-10-14"


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
            "employment_binding_id": None if kind == "payroll_policy" else binding["binding_id"],
            "month": month,
            "reference": reference, "filename": f"{kind}.pdf",
            "data_url": "data:application/pdf;base64," + base64.b64encode(raw).decode(),
            "evidence": "Synthetic source for byte verification test",
        })
        assert response.status_code == 200, response.text
        return response.json(), raw

    contract, _ = await upload("employment_contract", "signed-contract-2026-7")
    timesheet, _ = await upload("timesheet", "reviewed-timesheet-2026-10-7", "2026-10")
    schedule, schedule_raw = await upload("work_schedule", "approved-work-schedule-2026-10", "2026-10")
    adjustment, _ = await upload("base_adjustment", "synthetic-adjustment-source", "2026-10")
    policy_file, _ = await upload("payroll_policy", "synthetic-reviewed-payroll-policy")
    bad_rule = await client.post(
        f"/accounting/organizations/{book[0]}/payroll-rule-sets", json={
            "request_key": str(uuid4()), "policy_id": book[1],
            "effective_from": "2026-01-01", "gross_method": "monthly_salary_by_hours",
            "rounding": "half_up_cent", "rate_rules": ruleset["rate_rules"],
            "source_reference": policy_file["reference"],
            "source_digest": "0" * 64,
            "source_file_id": policy_file["file_id"],
            "evidence": "Synthetic accountant supplied file-backed payroll policy",
        },
    )
    assert bad_rule.status_code == 422
    new_rule = await client.post(
        f"/accounting/organizations/{book[0]}/payroll-rule-sets", json={
            "request_key": str(uuid4()), "policy_id": book[1],
            "effective_from": "2026-01-01", "gross_method": "monthly_salary_by_hours",
            "rounding": "half_up_cent", "rate_rules": ruleset["rate_rules"],
            "source_reference": policy_file["reference"],
            "source_digest": policy_file["sha256"],
            "source_file_id": policy_file["file_id"],
            "evidence": "Synthetic accountant supplied file-backed payroll policy",
        },
    )
    assert new_rule.status_code == 200, new_rule.text
    assert new_rule.json()["source_file_verified_at_configuration"] is True
    preview_url = f"/accounting/organizations/{book[0]}/periods/2026-10/payroll-workpaper-preview"
    args = (book[1], binding["binding_id"], deduction["requirement_id"],
            contribution["requirement_id"], new_rule.json()["rule_set_id"])
    fields = {
        "contract_file_id": contract["file_id"], "contract_digest": contract["sha256"],
        "timesheet_file_id": timesheet["file_id"], "timesheet_digest": timesheet["sha256"],
        "work_schedule_document": schedule["reference"],
        "work_schedule_digest": schedule["sha256"],
        "work_schedule_file_id": schedule["file_id"],
        "norm_hours_evidence": "Approved monthly norm in the work schedule",
    }
    reviewed_command = command(*args, **fields)
    reviewed_command["components"][1]["adjustment_file_id"] = adjustment["file_id"]
    missing_schedule = command(*args, **{key: value for key, value in fields.items()
                                       if not key.startswith("work_schedule")
                                       and key != "norm_hours_evidence"})
    missing_schedule["components"][1]["adjustment_file_id"] = adjustment["file_id"]
    preliminary = await client.post(preview_url, json=missing_schedule)
    assert preliminary.status_code == 200, preliminary.text
    assert preliminary.json()["schedule_file_bytes_verified"] is False
    accepted = await client.post(preview_url, json=reviewed_command)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["contract_and_timesheet_hashes_verified"] is True
    assert accepted.json()["schedule_file_bytes_verified"] is True
    assert accepted.json()["basis"]["work_schedule_file_id"] == schedule["file_id"]
    assert accepted.json()["basis"]["norm_hours_evidence"] == fields["norm_hours_evidence"]
    assert accepted.json()["rule_source_file_bytes_verified"] is True
    assert accepted.json()["basis"]["contract_file_id"] == contract["file_id"]

    schedule_path = root / str(book[0]) / (schedule["request_key"].replace("-", "") + ".pdf")
    schedule_path.write_bytes(b"%PDF-1.7\ntampered schedule\n")
    assert (await client.post(preview_url, json=reviewed_command)).status_code == 409
    schedule_path.write_bytes(schedule_raw)
    assert (await client.post(preview_url, json={
        **reviewed_command, "work_schedule_file_id": adjustment["file_id"],
    })).status_code == 422
    september_schedule, _ = await upload("work_schedule", "approved-work-schedule-2026-09", "2026-09")
    assert (await client.post(preview_url, json={
        **reviewed_command, "work_schedule_file_id": september_schedule["file_id"],
        "work_schedule_document": september_schedule["reference"],
        "work_schedule_digest": september_schedule["sha256"],
    })).status_code == 422

    xlsx_path = tmp_path / "october.xlsx"
    make_timesheet(xlsx_path, month="2026-10", coded_day=True)
    xlsx_upload = await client.post(url, json={
        "request_key": str(uuid4()), "kind": "timesheet",
        "employment_binding_id": binding["binding_id"], "month": "2026-10",
        "reference": "synthetic-october-xlsx", "filename": xlsx_path.name,
        "data_url": "data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,"
                    + base64.b64encode(xlsx_path.read_bytes()).decode(),
        "evidence": "Fictional row-level XLSX comparison",
    })
    assert xlsx_upload.status_code == 200, xlsx_upload.text
    xlsx_source = xlsx_upload.json()
    xlsx_command = {
        **reviewed_command,
        "work_to": "2026-10-02",
        "timesheet_document": xlsx_source["reference"],
        "timesheet_file_id": xlsx_source["file_id"],
        "timesheet_digest": xlsx_source["sha256"],
        "worked_hours": "8.00",
    }
    xlsx_command["components"] = [
        reviewed_command["components"][0],
        {**reviewed_command["components"][1], "adjustment_byn": "50.00"},
    ]
    assert (await client.post(preview_url, json=xlsx_command)).status_code == 422
    assert (await client.post(preview_url, json={
        **xlsx_command, "timesheet_row": 13,
    })).status_code == 422
    assert (await client.post(preview_url, json={
        **xlsx_command, "timesheet_row": 11, "worked_hours": "7.00",
    })).status_code == 422
    checked_xlsx = await client.post(preview_url, json={**xlsx_command, "timesheet_row": 11})
    assert checked_xlsx.status_code == 200, checked_xlsx.text
    assert checked_xlsx.json()["timesheet_numeric_hours_verified"] is True
    assert checked_xlsx.json()["basis"]["timesheet_row"] == 11
    assert checked_xlsx.json()["basis"]["timesheet_uninterpreted_code_days"] == 1

    review_url = f"/accounting/organizations/{book[0]}/periods/2026-10/payroll-workpaper-reviews"
    missing_schedule_review = await client.post(review_url, json={
        **missing_schedule, "request_key": str(uuid4()),
        "basis_digest": preliminary.json()["basis_digest"],
        "reviewer_evidence": "Synthetic preview lacks the monthly norm source",
    })
    assert missing_schedule_review.status_code == 422
    broken_path = tmp_path / "broken-october.xlsx"
    make_timesheet(broken_path, month="2026-10", truncated=True)
    broken_upload = await client.post(url, json={
        "request_key": str(uuid4()), "kind": "timesheet",
        "employment_binding_id": binding["binding_id"], "month": "2026-10",
        "reference": "synthetic-broken-october", "filename": broken_path.name,
        "data_url": "data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,"
                    + base64.b64encode(broken_path.read_bytes()).decode(),
        "evidence": "Fictional defective workbook for investigation",
    })
    assert broken_upload.status_code == 200, broken_upload.text
    broken_source = broken_upload.json()
    broken_command = {
        **xlsx_command,
        "timesheet_document": broken_source["reference"],
        "timesheet_file_id": broken_source["file_id"],
        "timesheet_digest": broken_source["sha256"],
    }
    investigation = await client.post(preview_url, json=broken_command)
    assert investigation.status_code == 200, investigation.text
    blocked_xlsx_review = await client.post(review_url, json={
        **broken_command, "request_key": str(uuid4()),
        "basis_digest": investigation.json()["basis_digest"],
        "reviewer_evidence": "Synthetic investigation of defective XLSX",
    })
    assert blocked_xlsx_review.status_code == 422
    assert await db.scalar(select(func.count(PayrollWorkpaperReview.id))) == 0

    review_command = {
        **reviewed_command,
        "request_key": str(uuid4()),
        "basis_digest": accepted.json()["basis_digest"],
        "reviewer_evidence": "Synthetic chief reviewed source-backed arithmetic only",
    }
    original_preflight = payroll_evidence_files.timesheet_preflight
    monkeypatch.setattr(payroll_evidence_files, "timesheet_preflight",
                        lambda _row: {"status": "structure_failed"})
    blocked = await client.post(review_url, json={**review_command, "request_key": str(uuid4())})
    assert blocked.status_code == 422
    assert "preflight" in blocked.text.lower()
    assert await db.scalar(select(func.count(PayrollWorkpaperReview.id))) == 0
    monkeypatch.setattr(payroll_evidence_files, "timesheet_preflight", original_preflight)
    reviewed = await client.post(review_url, json=review_command)
    assert reviewed.status_code == 200, reviewed.text
    receipt = reviewed.json()
    assert receipt["revision"] == 1
    assert receipt["bytes_verified_at_review"] is True
    assert receipt["current_file_bytes_verified"] is False
    assert receipt["posting_available"] is False
    assert receipt["statutory_payroll_certified"] is False
    assert receipt["snapshot"]["basis_digest"] == accepted.json()["basis_digest"]
    assert (await client.post(review_url, json=review_command)).json() == receipt
    assert (await client.get(
        f"/accounting/organizations/{book[0]}/payroll-workpaper-reviews/{review_command['request_key']}"
    )).json() == receipt
    assert await db.scalar(select(func.count(PayrollWorkpaperReview.id))) == 1
    assert (await client.post(review_url, json={
        **review_command, "reviewer_evidence": "Changed evidence on same key",
    })).status_code == 409
    assert (await client.post(review_url, json={
        **review_command, "request_key": str(uuid4()),
        "reviewer_evidence": "           ",
    })).status_code == 422

    overlapping_command = {**reviewed_command, "work_from": "2026-10-02"}
    overlapping_preview = await client.post(preview_url, json=overlapping_command)
    assert overlapping_preview.status_code == 200
    overlap = await client.post(review_url, json={
        **overlapping_command, "request_key": str(uuid4()),
        "basis_digest": overlapping_preview.json()["basis_digest"],
        "reviewer_evidence": "Synthetic review of an overlapping work segment",
    })
    assert overlap.status_code == 422
    assert "overlaps" in overlap.text

    corrected_command = {**reviewed_command, "monthly_salary_byn": "1600.00"}
    corrected_preview = await client.post(preview_url, json=corrected_command)
    assert corrected_preview.status_code == 200
    correction = {
        **corrected_command, "request_key": str(uuid4()),
        "basis_digest": corrected_preview.json()["basis_digest"],
        "reviewer_evidence": "Synthetic correction of the salary input source",
    }
    assert (await client.post(review_url, json=correction)).status_code == 422
    correction["supersedes_review_id"] = receipt["review_id"]
    corrected = await client.post(review_url, json=correction)
    assert corrected.status_code == 200, corrected.text
    assert corrected.json()["revision"] == 2
    assert corrected.json()["supersedes_review_id"] == receipt["review_id"]
    summary_url = f"/accounting/organizations/{book[0]}/periods/2026-10/payroll-arithmetic-summary"
    summary_response = await client.get(summary_url)
    assert summary_response.status_code == 200, summary_response.text
    summary = summary_response.json()
    assert summary_response.headers["cache-control"] == "private, no-store"
    assert summary["review_count"] == 2
    assert summary["selected_segment_count"] == 1
    assert summary["bindings"][0]["segments"][0]["review_id"] == corrected.json()["review_id"]
    assert summary["totals"] == {
        "gross_byn": "800.00",
        "listed_employee_deductions_byn": "80.00",
        "after_listed_deductions_byn": "720.00",
        "listed_employer_contributions_byn": "140.00",
        "cost_including_listed_contributions_byn": "940.00",
    }
    assert len(summary["selection_digest"]) == 64
    assert summary["coverage_verified"] is False
    assert summary["known_binding_coverage"]["known_binding_coverage_complete"] is True
    assert summary["known_binding_coverage"]["organization_payroll_population_verified"] is False
    assert summary["current_file_bytes_verified"] is True
    assert summary["posting_available"] is False
    assert summary["statutory_payroll_certified"] is False
    reconcile_url = (f"/accounting/organizations/{book[0]}/periods/2026-10/"
                     "payroll-source-reconciliation")
    empty_reconcile = await client.get(reconcile_url)
    assert empty_reconcile.status_code == 200, empty_reconcile.text
    assert empty_reconcile.headers["cache-control"] == "private, no-store"
    assert empty_reconcile.json()["status"] == "not_ready"
    assert empty_reconcile.json()["missing_gross_binding_ids"] == [binding["binding_id"]]

    for code, category in (("26", "expense"), ("70", "liability"),
                           ("68.1", "liability"), ("69", "liability")):
        db.add(Account(
            organization_id=book[0], code=code, title=f"Synthetic payroll {code}",
            category=category, valid_from=date(2026, 1, 1),
            required_dimensions=[], currency_tracking=False,
            quantity_tracking=False, cash=False, normative_ref="Synthetic payroll source",
        ))
    await db.commit()

    async def imported(kind, source_document, lines):
        body = {
            "request_key": str(uuid4()), "source_document": source_document,
            "source_version": 1, "source_digest": "b" * 64,
            "verified_by": "tester", "source_evidence": "Synthetic reviewed external payroll file",
            "policy_id": book[1], "posting_date": "2026-10-31",
            "payroll_account": "70", "lines": lines,
        }
        path = (f"/accounting/organizations/{book[0]}/periods/2026-10/"
                f"payroll-{kind}-import-")
        preview = await client.post(path + "preview", json=body)
        assert preview.status_code == 200, preview.text
        confirmed = await client.post(path + "confirm", json={
            **body, "digest": preview.json()["digest"],
        }, headers={"X-Expected-Principal": "tester"})
        assert confirmed.status_code == 201, confirmed.text
        await db.commit()

    await imported("accrual", "gross-reviewed", [{
        "source_line_id": "gross-1", "employment_binding_id": binding["binding_id"],
        "employee": "Synthetic Employee", "department": "repair",
        "debit_account": "26", "amount_byn": "800.00",
        "evidence": "Synthetic gross line from external payroll",
    }])
    without_statutory = (await client.get(reconcile_url)).json()
    assert without_statutory["comparison_ready"] is False
    assert without_statutory["missing_statutory_binding_ids"] == [binding["binding_id"]]
    await imported("statutory", "statutory-reviewed", [
        {"source_line_id": "deduction-1", "employment_binding_id": binding["binding_id"],
         "employee": "Synthetic Employee", "department": "repair",
         "kind": "employee_deduction", "liability_account": "68.1",
         "amount_byn": "80.00", "evidence": "Synthetic external deduction line"},
        {"source_line_id": "contribution-1", "employment_binding_id": binding["binding_id"],
         "employee": "Synthetic Employee", "department": "repair",
         "kind": "employer_contribution", "liability_account": "69",
         "cost_account": "26", "amount_byn": "140.00",
         "evidence": "Synthetic external contribution line"},
    ])
    no_roster = (await client.get(reconcile_url)).json()
    assert no_roster["status"] == "not_ready"
    assert no_roster["bindings"][0]["difference_import_less_review"] == {
        "gross_byn": "0.00", "listed_employee_deductions_byn": "0.00",
        "listed_employer_contributions_byn": "0.00",
    }
    roster_file = await client.post(url, json={
        "request_key": str(uuid4()), "kind": "payroll_population", "month": "2026-10",
        "reference": "one-worker-roster", "filename": "roster.pdf",
        "data_url": "data:application/pdf;base64," + base64.b64encode(
            b"%PDF-1.7\nsynthetic roster source\n").decode(),
        "evidence": "Synthetic chief reviewed the monthly employee roster",
    })
    assert roster_file.status_code == 200, roster_file.text
    roster_review = await client.post(
        f"/accounting/organizations/{book[0]}/periods/2026-10/payroll-population-reviews",
        json={
            "request_key": str(uuid4()), "source_file_id": roster_file.json()["file_id"],
            "source_system": "synthetic-hr", "source_document": "one-worker-roster",
            "source_employee_count": 1, "binding_ids": [binding["binding_id"]],
            "employee_ids": [binding["employee_id"]],
            "evidence": "Synthetic chief matched the employee to ERP binding",
        })
    assert roster_review.status_code == 200, roster_review.text
    matched = (await client.get(reconcile_url)).json()
    assert matched["status"] == "matched_arithmetic_only"
    assert matched["comparison_ready"] is True
    assert matched["current_file_bytes_verified"] is True
    assert matched["missing_statutory_binding_ids"] == []
    assert matched["statutory_payroll_certified"] is False
    assert matched["posting_available"] is False
    for source in (policy_file, contract, timesheet, adjustment):
        source_path = root / str(book[0]) / (source["request_key"].replace("-", "") + ".pdf")
        original = source_path.read_bytes()
        source_path.write_bytes(b"%PDF-1.7\ntampered after chief review\n")
        assert (await client.get(summary_url)).status_code == 409
        source_path.write_bytes(original)
    schedule_path.write_bytes(b"%PDF-1.7\ntampered after chief review\n")
    assert (await client.get(summary_url)).status_code == 409
    assert (await client.get(reconcile_url)).status_code == 409
    stale_controls = (await client.get(
        f"/accounting/organizations/{book[0]}/periods/2026-10/closing-controls")).json()
    assert stale_controls["payroll"]["arithmetic_reconciliation_status"] == "unavailable"
    assert "payroll_arithmetic_reconciliation_unavailable" in {
        item["code"] for item in stale_controls["review_items"]}
    historical = await client.get(
        f"/accounting/organizations/{book[0]}/payroll-workpaper-reviews/{review_command['request_key']}")
    assert historical.status_code == 200
    assert historical.json() == receipt
    schedule_path.write_bytes(schedule_raw)
    assert (await client.get(reconcile_url)).json()["comparison_ready"] is True
    first_gross_entry = matched["receipt_entry_ids"]["gross"][0]
    first_line = await db.scalar(select(Line).where(Line.entry_id == first_gross_entry)
                                 .order_by(Line.id))
    first_line_id = first_line.id
    await db.execute(update(Line).where(Line.id == first_line_id).values(amount="801.00"))
    await db.commit()
    assert (await client.get(reconcile_url)).status_code == 409
    await db.execute(update(Line).where(Line.id == first_line_id).values(amount="800.00"))
    await db.commit()
    await imported("accrual", "extra-gross-reviewed", [{
        "source_line_id": "extra-gross-1", "employment_binding_id": binding["binding_id"],
        "employee": "Synthetic Employee", "department": "repair",
        "debit_account": "26", "amount_byn": "10.00",
        "evidence": "Synthetic additional external gross line",
    }])
    changed = (await client.get(reconcile_url)).json()
    assert changed["status"] == "differences"
    assert changed["bindings"][0]["difference_import_less_review"]["gross_byn"] == "10.00"
    closing_controls = (await client.get(
        f"/accounting/organizations/{book[0]}/periods/2026-10/closing-controls")).json()
    assert closing_controls["payroll"]["arithmetic_reconciliation_status"] == "differences"
    assert "payroll_arithmetic_difference" in {
        item["code"] for item in closing_controls["review_items"]}
    grant = await db.scalar(select(AccessGrant).where(
        AccessGrant.organization_id == book[0], AccessGrant.subject == "tester"))
    grant.role = "reader"
    await db.commit()
    reader_controls = (await client.get(
        f"/accounting/organizations/{book[0]}/periods/2026-10/closing-controls")).json()
    assert reader_controls["payroll"]["arithmetic_reconciliation_status"] == "not_requested"
    assert "payroll_arithmetic_difference" not in {
        item["code"] for item in reader_controls["review_items"]}
    assert (await client.get(reconcile_url)).status_code == 403
    grant.role = "chief"
    await db.commit()
    assert (await client.post(review_url, json={
        **review_command, "request_key": str(uuid4()),
        "supersedes_review_id": receipt["review_id"],
    })).status_code == 422

    contradictory_zero = await client.post(url, json={
        "request_key": str(uuid4()), "kind": "payroll_stat_zero_person",
        "employment_binding_id": binding["binding_id"], "month": "2026-10",
        "reference": "contradictory-statutory-zero", "filename": "stat-zero.pdf",
        "data_url": "data:application/pdf;base64," + base64.b64encode(
            b"%PDF-1.7\nsynthetic contradictory statutory zero\n").decode(),
        "evidence": "Synthetic contradictory zero statement for mapped employee",
    })
    assert contradictory_zero.status_code == 200, contradictory_zero.text
    conflicted = (await client.get(reconcile_url)).json()
    assert conflicted["comparison_ready"] is False
    assert conflicted["conflicting_statutory_zero_binding_ids"] == [binding["binding_id"]]
    assert conflicted["statutory_person_zero_file_ids"] == [
        contradictory_zero.json()["file_id"]]

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
    stored_pdf_bytes = {path: path.read_bytes() for path in (root / str(book[0])).glob("*.pdf")}
    for path in stored_pdf_bytes:
        path.write_bytes(b"%PDF-1.7\ncorrupted")
    tampered = await client.post(preview_url, json=command(*args, **fields))
    assert tampered.status_code == 409
    assert (await client.get(summary_url)).status_code == 409
    for path, original in stored_pdf_bytes.items():
        path.write_bytes(original)
    ended_after_review = await client.post(
        f"/accounting/organizations/{book[0]}/payroll-employments", json={
            "request_key": str(uuid4()),
            "employee_id": binding["employee_id"],
            "contract_ref": binding["contract_ref"],
            "effective_from": "2026-10-15",
            "state": "ended",
            "source_document": "synthetic-retrospective-contract-end",
            "evidence": "Synthetic later correction to employment period",
        },
    )
    assert ended_after_review.status_code == 200, ended_after_review.text
    stale_summary = (await client.get(summary_url)).json()
    stale_coverage = stale_summary["known_binding_coverage"]
    assert stale_coverage["known_binding_coverage_complete"] is False
    assert stale_coverage["expected_intervals"][0]["work_to"] == "2026-10-14"
    assert stale_coverage["issues"][0]["kind"] == "outside_current_binding"
    assert stale_summary["selection_digest"] == summary["selection_digest"]
    assert stale_summary["coverage_digest"] != summary["coverage_digest"]
    assert stale_summary["summary_digest"] != summary["summary_digest"]

    period = await db.scalar(select(Period).where(
        Period.organization_id == book[0], Period.month == "2026-10"))
    period.closed = True
    await db.commit()
    assert (await client.post(review_url, json={
        **review_command, "request_key": str(uuid4()),
        "supersedes_review_id": corrected.json()["review_id"],
    })).status_code == 422
    assert (await client.post(review_url, json=review_command)).json() == receipt
    grant = await db.scalar(select(AccessGrant).where(
        AccessGrant.organization_id == book[0], AccessGrant.subject == "tester",
    ))
    grant.role = "accountant"
    await db.commit()
    accountant_access = (await client.get(
        f"/accounting/organizations/{book[0]}/payroll-workpaper-access",
    )).json()
    assert accountant_access == {"organization_id": book[0], "can_preview": True,
                                 "can_upload": True, "can_review": False}
    assert (await client.post(review_url, json=review_command)).status_code == 403
    assert (await client.get(
        f"/accounting/organizations/{book[0]}/payroll-workpaper-reviews/{review_command['request_key']}"
    )).status_code == 200
    assert (await client.get(summary_url)).status_code == 200
    immutable_receipt = await db.get(PayrollWorkpaperReview, receipt["review_id"])
    immutable_receipt.reviewer_evidence = "Attempted edit of reviewed history"
    with pytest.raises(ValueError, match="immutable"):
        await db.flush()
    await db.rollback()
