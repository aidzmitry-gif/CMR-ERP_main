"""Structural XLSX intake checks, using fictional timesheets only."""

import base64
import calendar
import json
from datetime import date
from uuid import uuid4
from zipfile import ZipFile

import pytest
from sqlalchemy import select

from modules.accounting.models import AccessGrant, Organization
from modules.accounting.timesheet_preflight import (
    UnsupportedWorkbook,
    _column,
    row_numeric_hours,
    scan,
)
from modules.hr.models import Employee


def make_timesheet(path, *, month="2026-06", truncated=False, duplicate=False,
                   wrong_days=False, row_after_gap=False, coded_day=False,
                   name_1="Employee A", hours_2=4):
    year, month_number = map(int, month.split("-"))
    days = calendar.monthrange(year, month_number)[1]
    day_columns = [_column(index) for index in range(5, 5 + days)]
    days_col = _column(5 + days)
    hours_col = _column(6 + days)
    last_column = day_columns[-4] if truncated else day_columns[-1]
    identifier_2 = "worker-a" if duplicate else "worker-b"
    header = "".join(
        f'<c r="{column}8"><v>{day}</v></c>'
        for day, column in enumerate(day_columns, 1)
    )
    extra_1 = f'<c r="{day_columns[-3]}11"><v>2</v></c>' if truncated else ""
    extra_2 = f'<c r="{day_columns[-2]}12"><v>3</v></c>' if truncated else ""
    code = '<c r="F11" t="inlineStr"><is><t>В</t></is></c>' if coded_day else ""
    hours_1 = "8"
    hours_2 = str(hours_2)
    days_1 = "1" if wrong_days or not truncated else "2"
    days_2 = "2" if truncated else "1"
    extra_row = (f'<row r="14"><c r="B14" t="inlineStr"><is><t>worker-c</t></is></c>'
                 f'<c r="C14" t="inlineStr"><is><t>Employee C</t></is></c>'
                 f'<c r="E14"><v>1</v></c><c r="{days_col}14"><v>1</v></c>'
                 f'<c r="{hours_col}14"><f>SUM(E14:{day_columns[-1]}14)</f><v>1</v></c>'
                 f'</row>') if row_after_gap else ""
    month_name = ("Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
                  "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь")[month_number - 1]
    sheet = f'''<?xml version="1.0" encoding="utf-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<sheetData>
 <row r="8">{header}<c r="{days_col}8" t="inlineStr"><is><t>Рабочее время</t></is></c><c r="{hours_col}8" t="inlineStr"><is><t>Часы</t></is></c></row>
 <row r="11"><c r="B11" t="inlineStr"><is><t>worker-a</t></is></c><c r="C11" t="inlineStr"><is><t>{name_1}</t></is></c><c r="E11"><v>8</v></c>{code}{extra_1}<c r="{days_col}11"><v>{days_1}</v></c><c r="{hours_col}11"><f t="shared" si="0" ref="{hours_col}11:{hours_col}12">SUM(E11:{last_column}11)</f><v>{hours_1}</v></c></row>
 <row r="12"><c r="B12" t="inlineStr"><is><t>{identifier_2}</t></is></c><c r="C12" t="inlineStr"><is><t>Employee B</t></is></c><c r="E12"><v>{hours_2}</v></c>{extra_2}<c r="{days_col}12"><v>{days_2}</v></c><c r="{hours_col}12"><f t="shared" si="0"/><v>{hours_2}</v></c></row>
 <row r="13"><c r="D13" t="inlineStr"><is><t>Total</t></is></c></row>
 {extra_row}
</sheetData></worksheet>'''
    workbook = f'''<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="{month_name} {year}" sheetId="1" r:id="rId1"/></sheets></workbook>'''
    rels = '''<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Target="worksheets/sheet1.xml" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"/></Relationships>'''
    with ZipFile(path, "w") as archive:
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", rels)
        archive.writestr("xl/worksheets/sheet1.xml", sheet)


def test_valid_shared_formula_and_uninterpreted_codes(tmp_path):
    path = tmp_path / "timesheet.xlsx"
    make_timesheet(path)
    result = scan(path, "2026-06")
    assert result["structure_ok"] is True
    assert result["employee_rows"] == 2
    assert result["employee_row_numbers"] == [11, 12]
    assert result["issues"] == []
    assert result["payroll_approved"] is False


def test_selected_row_hours_are_limited_to_interval_and_codes_remain_uninterpreted(tmp_path):
    path = tmp_path / "october.xlsx"
    make_timesheet(path, month="2026-10", coded_day=True)
    raw = path.read_bytes()
    selected = row_numeric_hours(raw, "2026-10", 11, date(2026, 10, 1), date(2026, 10, 2))
    assert selected["numeric_hours"] == "8.00"
    assert selected["uninterpreted_code_days"] == 1
    assert row_numeric_hours(raw, "2026-10", 11, date(2026, 10, 1),
                             date(2026, 10, 2), "  employee   A ")["row_name_matches_binding"] is True
    assert row_numeric_hours(raw, "2026-10", 11, date(2026, 10, 1),
                             date(2026, 10, 2), "Different Employee")["row_name_matches_binding"] is False
    assert "Employee A" not in str(selected)
    assert selected["employee_identity_verified"] is False
    assert selected["code_meanings_verified"] is False
    with pytest.raises(UnsupportedWorkbook):
        row_numeric_hours(raw, "2026-10", 13, date(2026, 10, 1), date(2026, 10, 2))
    with pytest.raises(UnsupportedWorkbook):
        row_numeric_hours(raw, "2026-10", 11, date(2026, 10, 1), date(2026, 11, 1))


def test_truncated_shared_formula_mismatch_and_duplicate_are_private(tmp_path):
    path = tmp_path / "timesheet.xlsx"
    make_timesheet(path, truncated=True, duplicate=True, wrong_days=True)
    result = scan(path, "2026-06")
    codes = [issue["code"] for issue in result["issues"]]
    assert codes.count("hours_formula_range") == 2
    assert codes.count("hours_total_mismatch") == 2
    assert codes.count("worked_days_requires_review") == 1
    assert codes.count("personnel_identifier_repeated") == 1
    assert not result["structure_ok"]
    printed = json.dumps(result)
    assert "Employee A" not in printed
    assert "worker-a" not in printed


def test_different_month_cannot_pass_on_matching_day_numbers(tmp_path):
    path = tmp_path / "timesheet.xlsx"
    make_timesheet(path)
    result = scan(path, "2026-09")
    assert not result["structure_ok"]
    assert "sheet_period_unconfirmed" in [item["code"] for item in result["issues"]]


def test_employee_after_blank_row_is_not_silently_ignored(tmp_path):
    path = tmp_path / "timesheet.xlsx"
    make_timesheet(path, row_after_gap=True)
    result = scan(path, "2026-06")
    assert result["employee_rows"] == 3
    assert "employee_rows_after_gap" in [item["code"] for item in result["issues"]]


async def test_stored_timesheet_preflight_keeps_scope_and_source_bytes(
        client, db, book, tmp_path, monkeypatch):
    root = tmp_path / "payroll"
    root.mkdir()
    monkeypatch.setenv("AIOS_PAYROLL_DATA_DIR", str(root.resolve()))
    employee = Employee(full_name="Synthetic Workbook Employee", department="repair")
    db.add(employee)
    await db.flush()
    await db.commit()
    binding = await client.post(
        f"/accounting/organizations/{book[0]}/payroll-employments", json={
            "request_key": str(uuid4()), "employee_id": employee.id,
            "contract_ref": "synthetic-timesheet-contract", "effective_from": "2026-01-01",
            "state": "active", "source_document": "synthetic-signed-contract",
            "evidence": "Synthetic binding for a workbook source test",
        })
    assert binding.status_code == 200, binding.text
    binding_id = binding.json()["binding_id"]

    async def upload(path):
        request_key = str(uuid4())
        response = await client.post(
            f"/accounting/organizations/{book[0]}/payroll-evidence-files", json={
                "request_key": request_key, "kind": "timesheet",
                "employment_binding_id": binding_id, "month": "2026-06",
                "reference": f"synthetic-{path.stem}", "filename": path.name,
                "data_url": "data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,"
                            + base64.b64encode(path.read_bytes()).decode(),
                "evidence": "Synthetic XLSX source for preflight API test",
            })
        assert response.status_code == 200, response.text
        return response.json(), request_key

    broken = tmp_path / "broken.xlsx"
    make_timesheet(broken, truncated=True, duplicate=True, wrong_days=True)
    bad_receipt, bad_key = await upload(broken)
    endpoint = (f"/accounting/organizations/{book[0]}/payroll-evidence-files/"
                f"{bad_receipt['file_id']}/timesheet-preflight")
    failed = await client.get(endpoint)
    assert failed.status_code == 200, failed.text
    body = failed.json()
    assert body["status"] == "structure_failed"
    assert body["organization_id"] == book[0]
    assert body["employment_binding_id"] == binding_id
    assert body["source_sha256"] == bad_receipt["sha256"]
    assert body["document_facts_verified"] is False
    assert failed.headers["cache-control"] == "private, no-store"
    assert {item["code"] for item in body["issues"]} >= {
        "hours_formula_range", "hours_total_mismatch", "personnel_identifier_repeated"}
    assert "Synthetic Workbook Employee" not in failed.text
    assert "worker-a" not in failed.text
    assert "worker-b" not in failed.text

    corrected = tmp_path / "corrected.xlsx"
    make_timesheet(corrected)
    good_receipt, _ = await upload(corrected)
    good = await client.get(
        f"/accounting/organizations/{book[0]}/payroll-evidence-files/"
        f"{good_receipt['file_id']}/timesheet-preflight")
    assert good.status_code == 200
    assert good.json()["status"] == "structure_checked"
    assert good.json()["structure_ok"] is True
    assert good.json()["employee_row_numbers"] == [11, 12]
    assert good.json()["payroll_approved"] is False

    manual = await client.post(
        f"/accounting/organizations/{book[0]}/payroll-evidence-files", json={
            "request_key": str(uuid4()), "kind": "timesheet",
            "employment_binding_id": binding_id, "month": "2026-06",
            "reference": "synthetic-signed-timesheet", "filename": "sheet.pdf",
            "data_url": "data:application/pdf;base64," + base64.b64encode(
                b"%PDF-1.7\nsynthetic signed timesheet\n").decode(),
            "evidence": "Synthetic PDF source requiring human review",
        })
    assert manual.status_code == 200
    manual_check = await client.get(
        f"/accounting/organizations/{book[0]}/payroll-evidence-files/"
        f"{manual.json()['file_id']}/timesheet-preflight")
    assert manual_check.status_code == 200
    assert manual_check.json()["status"] == "manual_source"
    assert manual_check.json()["structure_ok"] is None
    assert manual_check.json()["document_facts_verified"] is False

    unreadable = await client.post(
        f"/accounting/organizations/{book[0]}/payroll-evidence-files", json={
            "request_key": str(uuid4()), "kind": "timesheet",
            "employment_binding_id": binding_id, "month": "2026-06",
            "reference": "synthetic-unreadable-xlsx", "filename": "unreadable.xlsx",
            "data_url": "data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,"
                        + base64.b64encode(b"PK\x03\x04invalid-zip").decode(),
            "evidence": "Synthetic unreadable workbook for fail-closed check",
        })
    assert unreadable.status_code == 200
    unreadable_check = await client.get(
        f"/accounting/organizations/{book[0]}/payroll-evidence-files/"
        f"{unreadable.json()['file_id']}/timesheet-preflight")
    assert unreadable_check.status_code == 200
    assert unreadable_check.json()["status"] == "uncheckable"
    assert unreadable_check.json()["structure_ok"] is False

    storage = root / str(book[0]) / (bad_key.replace("-", "") + ".xlsx")
    storage.write_bytes(b"PK\x03\x04tampered")
    assert (await client.get(endpoint)).status_code == 409

    other = Organization(name="Other Timesheet Company", unp="456456456")
    db.add(other)
    await db.flush()
    db.add(AccessGrant(organization_id=other.id, subject="tester", role="accountant"))
    await db.commit()
    crossed = await client.get(
        f"/accounting/organizations/{other.id}/payroll-evidence-files/"
        f"{good_receipt['file_id']}/timesheet-preflight")
    assert crossed.status_code == 404
    grant = await db.scalar(select(AccessGrant).where(
        AccessGrant.organization_id == book[0], AccessGrant.subject == "tester"))
    grant.role = "reader"
    await db.commit()
    assert (await client.get(endpoint)).status_code == 403
