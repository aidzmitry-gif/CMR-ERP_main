"""Structural XLSX intake checks, using fictional timesheets only."""

import json
from zipfile import ZipFile

from scripts.accounting_timesheet_preflight import scan


def make_timesheet(path, *, truncated=False, duplicate=False, wrong_days=False,
                   row_after_gap=False):
    last_column = "AE" if truncated else "AH"
    identifier_2 = "worker-a" if duplicate else "worker-b"
    header = "".join(
        f'<c r="{column}8"><v>{day}</v></c>'
        for day, column in enumerate(
            ["E", "F", "G", "H", "I", "J", "K", "L", "M", "N", "O", "P",
             "Q", "R", "S", "T", "U", "V", "W", "X", "Y", "Z", "AA", "AB",
             "AC", "AD", "AE", "AF", "AG", "AH"], 1
        )
    )
    extra_1 = '<c r="AF11"><v>2</v></c>' if truncated else ""
    extra_2 = '<c r="AG12"><v>3</v></c>' if truncated else ""
    hours_1 = "8" if truncated else "10" if extra_1 else "8"
    hours_2 = "4" if truncated else "7" if extra_2 else "4"
    days_1 = "1" if wrong_days or not truncated else "2"
    days_2 = "2" if truncated else "1"
    extra_row = '''<row r="14"><c r="B14" t="inlineStr"><is><t>worker-c</t></is></c><c r="C14" t="inlineStr"><is><t>Employee C</t></is></c><c r="E14"><v>1</v></c><c r="AI14"><v>1</v></c><c r="AJ14"><f>SUM(E14:AH14)</f><v>1</v></c></row>''' if row_after_gap else ""
    sheet = f'''<?xml version="1.0" encoding="utf-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<sheetData>
 <row r="8">{header}<c r="AI8" t="inlineStr"><is><t>Рабочее время</t></is></c><c r="AJ8" t="inlineStr"><is><t>Часы</t></is></c></row>
 <row r="11"><c r="B11" t="inlineStr"><is><t>worker-a</t></is></c><c r="C11" t="inlineStr"><is><t>Employee A</t></is></c><c r="E11"><v>8</v></c>{extra_1}<c r="AI11"><v>{days_1}</v></c><c r="AJ11"><f t="shared" si="0" ref="AJ11:AJ12">SUM(E11:{last_column}11)</f><v>{hours_1}</v></c></row>
 <row r="12"><c r="B12" t="inlineStr"><is><t>{identifier_2}</t></is></c><c r="C12" t="inlineStr"><is><t>Employee B</t></is></c><c r="E12"><v>4</v></c>{extra_2}<c r="AI12"><v>{days_2}</v></c><c r="AJ12"><f t="shared" si="0"/><v>{hours_2}</v></c></row>
 <row r="13"><c r="D13" t="inlineStr"><is><t>Total</t></is></c></row>
 {extra_row}
</sheetData></worksheet>'''
    workbook = '''<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Июнь 2026" sheetId="1" r:id="rId1"/></sheets></workbook>'''
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
    assert result["issues"] == []
    assert result["payroll_approved"] is False


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
