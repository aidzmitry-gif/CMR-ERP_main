"""Fictional monthly schedules: a selected source cell must be literal hours."""
from zipfile import ZipFile

import pytest

from modules.accounting.timesheet_preflight import UnsupportedWorkbook
from modules.accounting.work_schedule_norm import numeric_norm


def make_schedule(path, *, title="Октябрь 2026", cell="<v>160</v>"):
    workbook = (
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets><sheet name="{title}" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    relationships = (
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Target="worksheets/sheet1.xml" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"/>'
        '</Relationships>'
    )
    sheet = (
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData><row r="5"><c r="B5">{cell}</c></row></sheetData></worksheet>'
    )
    with ZipFile(path, "w") as archive:
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", relationships)
        archive.writestr("xl/worksheets/sheet1.xml", sheet)


def test_selected_schedule_cell_is_exact_numeric_source(tmp_path):
    path = tmp_path / "schedule.xlsx"
    make_schedule(path)
    result = numeric_norm(path.read_bytes(), "2026-10", "B5")
    assert result["numeric_hours"] == "160.00"
    assert result["cell"] == "B5"
    assert result["schedule_approval_verified"] is False
    assert result["source_sha256"]


@pytest.mark.parametrize("title,cell,selected", [
    ("Сентябрь 2026", "<v>160</v>", "B5"),
    ("Октябрь 2026", "<f>SUM(A1:A2)</f><v>160</v>", "B5"),
    ("Октябрь 2026", "<v>160.001</v>", "B5"),
    ("Октябрь 2026", "<v>160</v>", "C5"),
])
def test_schedule_does_not_accept_wrong_period_formula_precision_or_cell(
        tmp_path, title, cell, selected):
    path = tmp_path / "schedule.xlsx"
    make_schedule(path, title=title, cell=cell)
    with pytest.raises(UnsupportedWorkbook):
        numeric_norm(path.read_bytes(), "2026-10", selected)
