"""Exact current employment snapshots for manual accounting analytics."""
from __future__ import annotations

from datetime import date

from modules.accounting import payroll_employment
from modules.accounting.models import PayrollEmploymentBinding
from modules.accounting.service import AccountingError

EMPLOYEE_SNAPSHOT_KEYS = {
    "employee",
    "employee_id",
    "employment_binding_id",
    "employee_contract_ref",
    "employee_binding_revision",
    "employee_binding_digest",
}
MAX_INTEGER_ID = 2_147_483_647


def _dimensions(binding: dict) -> dict[str, str]:
    return {
        "employee": binding["employee_name"],
        "employee_id": str(binding["employee_id"]),
        "employment_binding_id": str(binding["binding_id"]),
        "employee_contract_ref": binding["contract_ref"],
        "employee_binding_revision": str(binding["revision"]),
        "employee_binding_digest": binding["digest"],
    }


async def options(session, org_id: int, on: date, query: str | None) -> list[dict[str, str]]:
    term = (query or "").strip()
    if not term:
        return []
    if len(term) > 100:
        raise AccountingError("Employee search query is too long")
    needle = term.casefold()
    rows = await payroll_employment.effective(session, org_id, on)
    matches = []
    for row in rows:
        if row["state"] != "active":
            continue
        searchable = (row["employee_name"], row["contract_ref"], row["department"],
                      str(row["employee_id"]))
        if not any(needle in value.casefold() for value in searchable if isinstance(value, str)):
            continue
        matches.append({**_dimensions(row), "department": row["department"]})
        if len(matches) == 50:
            break
    return matches


async def verify(session, org_id: int, on: date, dimensions: dict[str, str]) -> None:
    if not (EMPLOYEE_SNAPSHOT_KEYS & dimensions.keys()):
        return
    if not EMPLOYEE_SNAPSHOT_KEYS <= dimensions.keys():
        raise AccountingError("Employee analytics require the complete current employment snapshot")
    if any(not isinstance(dimensions[key], str) or not dimensions[key].strip()
           for key in EMPLOYEE_SNAPSHOT_KEYS):
        raise AccountingError("Employee analytics require nonblank string snapshot values")

    employee_id = dimensions["employee_id"]
    binding_id = dimensions["employment_binding_id"]
    revision = dimensions["employee_binding_revision"]
    if (not employee_id.isascii() or not employee_id.isdecimal() or employee_id.startswith("0")
            or not binding_id.isascii() or not binding_id.isdecimal() or binding_id.startswith("0")
            or not revision.isascii() or not revision.isdecimal() or revision.startswith("0")
            or len(dimensions["employee_binding_digest"]) != 64
            or any(char not in "0123456789abcdef" for char in dimensions["employee_binding_digest"])):
        raise AccountingError("Employee analytics contain an invalid employment snapshot key")
    if any(int(value) > MAX_INTEGER_ID for value in (employee_id, binding_id, revision)):
        raise AccountingError("Employee analytics contain an invalid employment snapshot key")

    binding = await session.get(PayrollEmploymentBinding, int(binding_id))
    if binding is None or binding.organization_id != org_id or binding.effective_from > on:
        raise AccountingError("Employee must be selected from this organization's current employment register")
    current = await payroll_employment.current(
        session, org_id, binding.employee_id, binding.contract_ref, on,
    )
    if current is None:
        raise AccountingError("Employee has no employment binding on the operation date")
    selected_result = payroll_employment.result(binding)
    if binding.state != "active" or current.id != binding.id:
        raise AccountingError("Employment binding is ended or outdated; select the current employee again")

    expected = _dimensions(selected_result)
    if any(dimensions[key] != expected[key] for key in EMPLOYEE_SNAPSHOT_KEYS):
        raise AccountingError("Employee snapshot changed; select the current employee again")
    if "department" in dimensions and dimensions["department"] != selected_result["department"]:
        raise AccountingError("Employee department must match the selected employment snapshot")
