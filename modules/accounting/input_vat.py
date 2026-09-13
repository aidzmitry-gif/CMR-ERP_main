"""Review worksheet for posted input-VAT lines, not a deduction/tax register."""
from decimal import Decimal, InvalidOperation

from sqlalchemy import or_, select

from modules.accounting.models import Entry, InputVatRegisterEntry, Line
from modules.accounting.service import AccountingError, lock_organization


async def worksheet(session, org_id, start, end):
    if end < start:
        raise AccountingError("End precedes start")
    await lock_organization(session, org_id)
    records = (await session.execute(select(Entry, Line).join(Line, Line.entry_id == Entry.id).where(
        Entry.organization_id == org_id, Entry.posting_date >= start, Entry.posting_date <= end,
        or_(Line.account_code == "18", Line.account_code.like("18.%")),
    ).order_by(Entry.posting_date, Entry.id, Line.id))).all()
    line_ids = [line.id for _, line in records]
    registered = {}
    if line_ids:
        register_rows = (await session.scalars(select(InputVatRegisterEntry).where(
            InputVatRegisterEntry.organization_id == org_id,
            InputVatRegisterEntry.line_id.in_(line_ids),
        ))).all()
        registered = {row.line_id: row for row in register_rows}
    rows = []
    totals = {"debit": Decimal(0), "credit": Decimal(0), "opening_debit": Decimal(0), "opening_credit": Decimal(0)}
    for entry, line in records:
        register = registered.get(line.id)
        dimensions = line.dimensions or {}
        issues = []
        raw_rate = dimensions.get("vat_rate")
        try:
            rate = Decimal(str(raw_rate))
            if not rate.is_finite() or rate < 0 or rate > 100:
                raise ValueError()
        except (InvalidOperation, ValueError):
            issues.append("missing_or_invalid_vat_rate")
        basis = dimensions.get("vat_basis")
        if not isinstance(basis, str) or not basis.strip():
            issues.append("missing_vat_basis")
        totals[("opening_" if entry.opening else "") + line.side] += line.amount
        rows.append({"entry_id": entry.id, "line_id": line.id, "source": entry.source,
                     "source_version": entry.source_version, "operation": entry.operation,
                     "posting_date": entry.posting_date,
                     "document_date": entry.document_date, "operation_date": entry.operation_date,
                     "opening": entry.opening, "correction_of": entry.correction_of,
                     "account_code": line.account_code, "account_title": line.account_title,
                     "side": line.side, "amount": format(line.amount, ".2f"),
                     "dimensions": dimensions, "review_issues": issues,
                     "deduction_status": register.deduction_status if register else "not_assessed",
                     "register_id": register.id if register else None,
                     "register_tax_period": register.tax_period if register else None,
                     "register_eschf_status": register.eschf_status if register else None,
                     "register_eschf_identifier": register.eschf_identifier if register else None,
                     "register_digest": register.digest if register else None,
                     "entry_digest": entry.digest,
                     "registered": register is not None})
    return {"organization_id": org_id, "start": start, "end": end, "status": "review_worksheet",
            "statutory_certified": False, "deduction_assessed": False, "rows": rows,
            "totals": {key: format(value, ".2f") for key, value in totals.items()},
            "rows_needing_metadata_review": sum(bool(row["review_issues"]) for row in rows),
            "rows_needing_register_review": sum(not row["registered"] for row in rows),
            "register_statutory_certified": False}
