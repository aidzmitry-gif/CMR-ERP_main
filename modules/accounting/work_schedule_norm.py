"""Read one explicit, literal norm-hours cell from a monthly XLSX schedule.

This checks a source number, not the schedule's approval or legal applicability.
"""
from __future__ import annotations

import hashlib
import re
from decimal import Decimal
from io import BytesIO
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile

from modules.accounting.timesheet_preflight import (
    MAIN,
    MAX_FILE_BYTES,
    MONTH_RU,
    NS,
    UnsupportedWorkbook,
    _number,
    _shared_strings,
    _sheet,
)

CELL = re.compile(r"[A-Z]{1,3}[1-9][0-9]{0,6}\Z")


def numeric_norm(raw: bytes, month: str, cell_ref: str) -> dict:
    """Return a checked cell value, without disclosing other workbook cells."""
    if len(raw) > MAX_FILE_BYTES or not CELL.fullmatch(cell_ref):
        raise UnsupportedWorkbook("Monthly schedule or cell is unsupported")
    try:
        year, number = map(int, month.split("-"))
        if month != f"{year:04d}-{number:02d}" or not 1 <= number <= 12:
            raise ValueError
    except ValueError as exc:
        raise UnsupportedWorkbook("Monthly schedule period is invalid") from exc
    try:
        with ZipFile(BytesIO(raw)) as archive:
            title, sheet = _sheet(archive)
            strings = _shared_strings(archive)
    except (BadZipFile, ET.ParseError) as exc:
        raise UnsupportedWorkbook("Monthly schedule XLSX is unreadable") from exc
    title = " ".join(title.casefold().split())
    iso_period = re.search(rf"(?<!\d){re.escape(month)}(?!\d)", title)
    named_period = re.search(rf"{MONTH_RU[number - 1]}\s+{year}(?!\d)", title)
    if not iso_period and not named_period:
        raise UnsupportedWorkbook("Monthly schedule sheet period does not match")
    cells = [cell for cell in sheet.findall("x:sheetData/x:row/x:c", NS)
             if cell.get("r") == cell_ref]
    if len(cells) != 1 or cells[0].find(f"{{{MAIN}}}f") is not None:
        raise UnsupportedWorkbook("Monthly schedule requires one literal norm cell")
    value = _number(cells[0], strings)
    if (value is None or not 0 < value <= 744
            or value != value.quantize(Decimal("0.01"))):
        raise UnsupportedWorkbook("Monthly schedule norm cell is not valid hours")
    return {
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "period": month,
        "cell": cell_ref,
        "numeric_hours": format(value, ".2f"),
        "schedule_approval_verified": False,
    }
