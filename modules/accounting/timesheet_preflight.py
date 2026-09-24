"""Read-only structural preflight for the accountant's monthly XLSX timesheet.

This checks spreadsheet arithmetic, not employee identity or payroll eligibility.
No names, personnel numbers, or cell contents are emitted in the result.
"""

from __future__ import annotations

import calendar
import hashlib
import posixpath
import re
import unicodedata
from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS = {"x": MAIN}
MONTH_RU = (
    "январь", "февраль", "март", "апрель", "май", "июнь",
    "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь",
)
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_XML_BYTES = 20 * 1024 * 1024
FORMULA = re.compile(r"SUM\(\s*([A-Z]+)(\d+)\s*:\s*([A-Z]+)(\d+)\s*\)", re.I)
CELL_REF = re.compile(r"([A-Z]+)(\d+)$")


class UnsupportedWorkbook(ValueError):
    """The workbook cannot be checked without guessing its contents."""


def _xml(archive: ZipFile, member: str) -> ET.Element:
    try:
        info = archive.getinfo(member)
    except KeyError as exc:
        raise UnsupportedWorkbook(f"missing XLSX member: {member}") from exc
    if info.file_size > MAX_XML_BYTES:
        raise UnsupportedWorkbook("XLSX XML member exceeds size limit")
    return ET.fromstring(archive.read(member))


def _column(number: int) -> str:
    chars = ""
    while number:
        number, rest = divmod(number - 1, 26)
        chars = chr(65 + rest) + chars
    return chars


def _shared_strings(archive: ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = _xml(archive, "xl/sharedStrings.xml")
    return ["".join(node.text or "" for node in item.iter(f"{{{MAIN}}}t"))
            for item in root.findall("x:si", NS)]


def _value(cell: ET.Element | None, strings: list[str]) -> str:
    if cell is None:
        return ""
    kind = cell.get("t")
    if kind == "inlineStr":
        return "".join(node.text or "" for node in cell.iter(f"{{{MAIN}}}t"))
    raw = cell.findtext("x:v", default="", namespaces=NS)
    if kind == "s" and raw:
        try:
            return strings[int(raw)]
        except (IndexError, ValueError) as exc:
            raise UnsupportedWorkbook("invalid shared-string reference") from exc
    return raw


def _number(cell: ET.Element | None, strings: list[str]) -> Decimal | None:
    if cell is None or cell.get("t") not in (None, "n"):
        return None
    raw = _value(cell, strings)
    if not raw:
        return None
    try:
        number = Decimal(raw)
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def _normalized_name(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _sheet(archive: ZipFile) -> tuple[str, ET.Element]:
    workbook = _xml(archive, "xl/workbook.xml")
    sheets = workbook.findall("x:sheets/x:sheet", NS)
    if len(sheets) != 1:
        raise UnsupportedWorkbook("exactly one timesheet is required")
    sheet = sheets[0]
    relationship_id = sheet.get(f"{{{REL}}}id")
    rels = _xml(archive, "xl/_rels/workbook.xml.rels")
    targets = [node.get("Target") for node in rels if node.get("Id") == relationship_id]
    if len(targets) != 1 or not targets[0]:
        raise UnsupportedWorkbook("missing worksheet relationship")
    target = targets[0]
    if target.startswith("/"):
        member = target.lstrip("/")
    else:
        member = posixpath.normpath(posixpath.join("xl", target))
    if not member.startswith("xl/worksheets/"):
        raise UnsupportedWorkbook("unsupported worksheet relationship")
    return sheet.get("name", ""), _xml(archive, member)


def _cells(root: ET.Element) -> dict[int, dict[str, ET.Element]]:
    rows: dict[int, dict[str, ET.Element]] = {}
    for row in root.findall("x:sheetData/x:row", NS):
        row_number = int(row.get("r", "0"))
        if row_number < 8:
            continue
        cells = {}
        for cell in row.findall("x:c", NS):
            ref = cell.get("r", "")
            if CELL_REF.fullmatch(ref):
                cells[ref] = cell
        rows[row_number] = cells
    return rows


def _resolved_formula(cell: ET.Element | None, row: int,
                      shared: dict[str, tuple[int, str]]) -> str | None:
    if cell is None:
        return None
    formula = cell.find("x:f", NS)
    if formula is None:
        return None
    expression = (formula.text or "").strip().lstrip("=")
    if expression:
        if formula.get("t") == "shared" and formula.get("si"):
            shared[formula.get("si", "")] = (row, expression)
        return expression
    if formula.get("t") != "shared" or formula.get("si") not in shared:
        return None
    anchor_row, anchor = shared[formula.get("si", "")]
    match = FORMULA.fullmatch(anchor)
    if match is None or int(match[2]) != anchor_row or int(match[4]) != anchor_row:
        return None
    return f"SUM({match[1]}{row}:{match[3]}{row})"


def _workbook(raw: bytes) -> tuple[str, dict[int, dict[str, ET.Element]], list[str]]:
    try:
        with ZipFile(BytesIO(raw)) as archive:
            title, sheet = _sheet(archive)
            strings = _shared_strings(archive)
    except (BadZipFile, ET.ParseError) as exc:
        raise UnsupportedWorkbook("invalid XLSX package") from exc
    return title, _cells(sheet), strings


def scan_bytes(raw: bytes, month: str) -> dict:
    try:
        year, month_number = map(int, month.split("-"))
        period = date(year, month_number, 1)
        if month != period.strftime("%Y-%m"):
            raise ValueError
    except ValueError as exc:
        raise UnsupportedWorkbook("month must be YYYY-MM") from exc
    if len(raw) > MAX_FILE_BYTES:
        raise UnsupportedWorkbook("XLSX file exceeds size limit")

    digest = hashlib.sha256(raw).hexdigest()
    title, rows, strings = _workbook(raw)
    issues: list[dict] = []
    warnings: list[dict] = []

    def issue(code: str, row_numbers: list[int] | None = None) -> None:
        issues.append({"code": code, "rows": row_numbers or []})

    title_normalized = " ".join(title.casefold().split())
    expected_title = f"{MONTH_RU[month_number - 1]} {year}"
    if expected_title not in title_normalized and month not in title_normalized:
        issue("sheet_period_unconfirmed")

    days = calendar.monthrange(year, month_number)[1]
    day_columns = [_column(n) for n in range(5, 5 + days)]
    days_col = _column(5 + days)
    hours_col = _column(6 + days)
    headers = rows.get(8, {})
    for day, column in enumerate(day_columns, 1):
        if _number(headers.get(f"{column}8"), strings) != day:
            issue("day_header_mismatch")
            break
    if (_value(headers.get(f"{days_col}8"), strings).strip().casefold() != "рабочее время"
            or _value(headers.get(f"{hours_col}8"), strings).strip().casefold() != "часы"):
        issue("summary_header_mismatch")

    identifiers: dict[str, list[int]] = defaultdict(list)
    shared_formulas: dict[str, tuple[int, str]] = {}
    employee_rows = 0
    employee_row_numbers: list[int] = []
    code_cells = 0
    started = False
    gap_seen = False
    for row_number in sorted(number for number in rows if number >= 11):
        cells = rows[row_number]
        relevant = [f"{column}{row_number}" for column in
                    ("B", "C", *day_columns, days_col, hours_col)]
        if not any(_value(cells.get(ref), strings).strip() for ref in relevant):
            if started:
                gap_seen = True
            continue
        if gap_seen:
            issue("employee_rows_after_gap", [row_number])
        started = True
        employee_rows += 1
        employee_row_numbers.append(row_number)
        identifier = _value(cells.get(f"B{row_number}"), strings).strip().casefold()
        if identifier:
            identifiers[identifier].append(row_number)
        else:
            issue("personnel_identifier_missing", [row_number])
        if not _value(cells.get(f"C{row_number}"), strings).strip():
            issue("employee_name_missing", [row_number])

        numeric_hours = Decimal(0)
        positive_days = 0
        for column in day_columns:
            cell = cells.get(f"{column}{row_number}")
            if cell is not None and cell.find("x:f", NS) is not None:
                issue("formula_in_day_cell", [row_number])
            numeric = _number(cell, strings)
            if numeric is not None:
                if numeric < 0 or numeric > 24:
                    issue("invalid_daily_hours", [row_number])
                numeric_hours += numeric
                positive_days += numeric > 0
            elif _value(cell, strings).strip():
                code_cells += 1

        reported_days = _number(cells.get(f"{days_col}{row_number}"), strings)
        if (reported_days is None or reported_days != int(reported_days)
                or reported_days < 0 or reported_days > days):
            issue("worked_days_invalid", [row_number])
        elif reported_days != positive_days:
            issue("worked_days_requires_review", [row_number])

        hours_cell = cells.get(f"{hours_col}{row_number}")
        formula = _resolved_formula(hours_cell, row_number, shared_formulas)
        match = FORMULA.fullmatch(formula or "")
        if (match is None or match[1].upper() != "E"
                or match[3].upper() != day_columns[-1]
                or int(match[2]) != row_number or int(match[4]) != row_number):
            issue("hours_formula_range", [row_number])
        cached_hours = _number(hours_cell, strings)
        if cached_hours is None:
            issue("hours_cache_missing", [row_number])
        elif cached_hours != numeric_hours:
            issue("hours_total_mismatch", [row_number])

    for repeated_rows in identifiers.values():
        if len(repeated_rows) > 1:
            issue("personnel_identifier_repeated", repeated_rows)
    if not employee_rows:
        issue("employee_rows_missing")
    if code_cells:
        warnings.append({"code": "day_codes_uninterpreted", "cell_count": code_cells})
    return {
        "source_sha256": digest,
        "period": month,
        "sheet_count": 1,
        "employee_rows": employee_rows,
        "employee_row_numbers": employee_row_numbers,
        "structure_ok": not issues,
        "payroll_approved": False,
        "issues": issues,
        "warnings": warnings,
    }


def row_numeric_hours(raw: bytes, month: str, row_number: int,
                      work_from: date, work_to: date,
                      expected_employee_name: str | None = None) -> dict:
    """Check selected numeric hours and name; neither proves employee identity."""
    report = scan_bytes(raw, month)
    if not report["structure_ok"]:
        raise UnsupportedWorkbook("timesheet structure is not accepted")
    if (type(row_number) is not int or row_number not in report["employee_row_numbers"]
            or work_from > work_to or work_from.strftime("%Y-%m") != month
            or work_to.strftime("%Y-%m") != month):
        raise UnsupportedWorkbook("timesheet row or work interval is outside this source")
    _, rows, strings = _workbook(raw)
    cells = rows[row_number]
    row_name = _value(cells.get(f"C{row_number}"), strings)
    name_matches = bool(expected_employee_name and _normalized_name(row_name)
                        and _normalized_name(row_name) == _normalized_name(expected_employee_name))
    hours = Decimal(0)
    coded_days = 0
    for day in range(work_from.day, work_to.day + 1):
        cell = cells.get(f"{_column(4 + day)}{row_number}")
        value = _number(cell, strings)
        if value is not None:
            hours += value
        elif _value(cell, strings).strip():
            coded_days += 1
    return {
        "row_number": row_number,
        "work_from": work_from.isoformat(),
        "work_to": work_to.isoformat(),
        "numeric_hours": format(hours, ".2f"),
        "uninterpreted_code_days": coded_days,
        "source_sha256": report["source_sha256"],
        "row_name_matches_binding": name_matches,
        "employee_identity_verified": False,
        "code_meanings_verified": False,
    }


def scan(path: Path, month: str) -> dict:
    if path.suffix.lower() != ".xlsx":
        raise UnsupportedWorkbook("expected an XLSX file")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise UnsupportedWorkbook("XLSX file exceeds size limit")
    return scan_bytes(path.read_bytes(), month)
