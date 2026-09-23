"""Stable employer identity for external payroll lines, without inferring ownership."""
from __future__ import annotations

from datetime import date

from sqlalchemy import select

from modules.accounting.models import PayrollEmploymentBinding
from modules.accounting.payroll_employment import result as employment_result
from modules.accounting.service import AccountingError


def canonical_line(line) -> dict:
    """Preserve the exact legacy command shape for still-unmapped receipts."""
    value = line.model_dump(mode="json")
    if value.get("employment_binding_id") is None:
        value.pop("employment_binding_id", None)
    return value


def canonical_command(data) -> dict:
    value = data.model_dump(mode="json")
    value["lines"] = [canonical_line(line) for line in data.lines]
    return value


async def verify_lines(session, org_id: int, through: date, lines) -> dict:
    """Check every supplied binding against its immutable employer snapshot."""
    ids = {line.employment_binding_id for line in lines
           if line.employment_binding_id is not None}
    if not ids:
        return {"mapped_line_count": 0, "mapped_binding_ids": [],
                "all_lines_mapped": False}
    rows = (await session.scalars(select(PayrollEmploymentBinding).where(
        PayrollEmploymentBinding.organization_id == org_id,
        PayrollEmploymentBinding.id.in_(ids),
    ))).all()
    by_id = {row.id: row for row in rows}
    if set(by_id) != ids:
        raise AccountingError("Payroll source line references another or unknown employer binding")
    for line in lines:
        binding_id = line.employment_binding_id
        if binding_id is None:
            continue
        row = by_id[binding_id]
        source = employment_result(row)
        if row.effective_from > through:
            raise AccountingError("Payroll employer binding starts after the source month")
        if line.employee != source["employee_name"]:
            raise AccountingError("Payroll employee name differs from the bound employer source")
    return {"mapped_line_count": sum(line.employment_binding_id is not None for line in lines),
            "mapped_binding_ids": sorted(ids),
            "all_lines_mapped": len(ids) > 0 and all(
                line.employment_binding_id is not None for line in lines)}
