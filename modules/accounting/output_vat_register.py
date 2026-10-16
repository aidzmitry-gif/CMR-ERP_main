"""Explicit evidence register for accrued output VAT.

The register is intentionally separate from sale posting.  It records the
accountant's reviewed tax period, treatment, ESCHF and export evidence for an
already posted 90.2 line; it never changes revenue, payment or the ledger.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator
from sqlalchemy import or_, select

from modules.accounting import service
from modules.accounting.models import Entry, Line, OutputVatRegisterEntry, Period
from modules.accounting.schemas import Input


class OutputVatRegisterInput(Input):
    request_key: UUID
    entry_id: int = Field(gt=0, strict=True)
    line_id: int = Field(gt=0, strict=True)
    expected_entry_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    tax_period: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    invoice_reference: str = Field(min_length=1, max_length=200)
    tax_treatment: Literal["not_assessed", "pending", "standard", "zero_export", "exempt", "not_subject"]
    eschf_identifier: str | None = Field(default=None, max_length=200)
    eschf_status: Literal["not_provided", "provided", "not_required", "pending"]
    treatment_basis: str = Field(min_length=10, max_length=2000)
    export_evidence: str | None = Field(default=None, max_length=2000)
    evidence: str = Field(min_length=10, max_length=2000)

    @model_validator(mode="after")
    def validate_explicit_evidence(self):
        if self.eschf_status == "provided" and not self.eschf_identifier:
            raise ValueError("ЭСЧФ identifier is required when the document is provided")
        if self.eschf_status != "provided" and self.eschf_identifier:
            raise ValueError("ЭСЧФ identifier requires the provided document status")
        if self.tax_treatment == "zero_export" and not self.export_evidence:
            raise ValueError("Zero-export treatment requires explicit export evidence")
        if self.tax_treatment != "zero_export" and self.export_evidence:
            raise ValueError("Export evidence is allowed only for zero-export treatment")
        return self


class OutputVatRegisterConfirmInput(OutputVatRegisterInput):
    digest: str = Field(pattern=r"^[a-f0-9]{64}$")


def _period(value: str) -> str:
    try:
        parsed = date.fromisoformat(value + "-01")
    except ValueError as exc:
        raise service.AccountingError("Tax period must be YYYY-MM") from exc
    if parsed.strftime("%Y-%m") != value:
        raise service.AccountingError("Tax period must be YYYY-MM")
    return value


def _digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()


def serialize_row(row: OutputVatRegisterEntry) -> dict:
    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "request_key": row.request_key,
        "entry_id": row.entry_id,
        "line_id": row.line_id,
        "source": row.source,
        "source_version": row.source_version,
        "entry_digest": row.entry_digest,
        "posting_date": row.posting_date,
        "tax_period": row.tax_period,
        "amount": format(row.amount, ".2f"),
        "currency": row.currency,
        "side": row.side,
        "invoice_reference": row.invoice_reference,
        "eschf_identifier": row.eschf_identifier,
        "tax_treatment": row.tax_treatment,
        "eschf_status": row.eschf_status,
        "treatment_basis": row.treatment_basis,
        "export_evidence": row.export_evidence,
        "evidence": row.evidence,
        "command": row.command,
        "digest": row.digest,
        "actor": row.actor,
        "created_at": row.created_at,
        "statutory_certified": False,
    }


async def worksheet(session, org_id: int, start: date, end: date) -> dict:
    """Return posted 90.2 lines with explicit register state for accountant review."""
    if end < start:
        raise service.AccountingError("End precedes start")
    await service.lock_organization(session, org_id)
    records = (await session.execute(select(Entry, Line).join(
        Line, Line.entry_id == Entry.id,
    ).where(
        Entry.organization_id == org_id,
        Entry.posting_date >= start,
        Entry.posting_date <= end,
        or_(Line.account_code == "90.2", Line.account_code.like("90.2.%")),
    ).order_by(Entry.posting_date, Entry.id, Line.id))).all()
    line_ids = [line.id for _, line in records]
    registered = {}
    if line_ids:
        register_rows = (await session.scalars(select(OutputVatRegisterEntry).where(
            OutputVatRegisterEntry.organization_id == org_id,
            OutputVatRegisterEntry.line_id.in_(line_ids),
        ))).all()
        registered = {row.line_id: row for row in register_rows}
    rows = []
    totals = {"debit": Decimal("0"), "credit": Decimal("0"),
              "opening_debit": Decimal("0"), "opening_credit": Decimal("0")}
    for entry, line in records:
        register = registered.get(line.id)
        dimensions = line.dimensions or {}
        issues = []
        if line.side != "debit":
            issues.append("output_vat_source_must_be_debit")
        if line.amount <= Decimal("0"):
            issues.append("output_vat_source_must_be_positive")
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
        rows.append({
            "entry_id": entry.id, "line_id": line.id, "source": entry.source,
            "source_version": entry.source_version, "operation": entry.operation,
            "posting_date": entry.posting_date, "document_date": entry.document_date,
            "operation_date": entry.operation_date, "opening": entry.opening,
            "correction_of": entry.correction_of, "account_code": line.account_code,
            "account_title": line.account_title, "side": line.side,
            "amount": format(line.amount, ".2f"), "currency": line.currency,
            "dimensions": dimensions, "review_issues": issues,
            "tax_treatment": register.tax_treatment if register else "not_assessed",
            "register_id": register.id if register else None,
            "register_tax_period": register.tax_period if register else None,
            "register_eschf_status": register.eschf_status if register else None,
            "register_eschf_identifier": register.eschf_identifier if register else None,
            "register_digest": register.digest if register else None,
            "entry_digest": entry.digest, "registered": register is not None,
        })
    return {
        "organization_id": org_id, "start": start, "end": end,
        "status": "review_worksheet", "statutory_certified": False,
        "vat_treatment_verified": False, "rows": rows,
        "totals": {key: format(value, ".2f") for key, value in totals.items()},
        "rows_needing_metadata_review": sum(bool(row["review_issues"]) for row in rows),
        "rows_needing_register_review": sum(not row["registered"] for row in rows),
        "register_statutory_certified": False,
    }


async def _source(session, org_id: int, data: OutputVatRegisterInput):
    _period(data.tax_period)
    entry = await session.scalar(select(Entry).where(
        Entry.organization_id == org_id, Entry.id == data.entry_id,
    ))
    line = await session.scalar(select(Line).where(
        Line.id == data.line_id, Line.entry_id == data.entry_id,
    ))
    if entry is None or line is None:
        raise service.AccountingError("Output-VAT source line was not found in this organization")
    if entry.digest != data.expected_entry_digest:
        raise service.AccountingError("The source posting changed; read it again")
    if not line.account_code == "90.2" and not line.account_code.startswith("90.2."):
        raise service.AccountingError("The selected source line is not an accrued-output-VAT account")
    if line.side != "debit" or line.amount <= Decimal("0"):
        raise service.AccountingError("Output-VAT source must be a positive debit line")
    closed = await session.scalar(select(Period.id).where(
        Period.organization_id == org_id, Period.month == data.tax_period, Period.closed.is_(True),
    ))
    if closed is not None:
        raise service.AccountingError("Reopen the tax period before adding a register classification")
    return entry, line


async def prepare_register(session, org_id: int, data: OutputVatRegisterInput) -> dict:
    entry, line = await _source(session, org_id, data)
    command = data.model_dump(mode="json", exclude={"digest"})
    source = {
        "entry_id": entry.id,
        "line_id": line.id,
        "source": entry.source,
        "source_version": entry.source_version,
        "entry_digest": entry.digest,
        "posting_date": entry.posting_date.isoformat(),
        "document_date": entry.document_date.isoformat(),
        "operation_date": entry.operation_date.isoformat(),
        "side": line.side,
        "amount": format(line.amount, ".2f"),
        "currency": line.currency,
        "account_code": line.account_code,
    }
    digest = _digest({"command": command, "source": source})
    existing = await session.scalar(select(OutputVatRegisterEntry).where(
        OutputVatRegisterEntry.organization_id == org_id,
        OutputVatRegisterEntry.entry_id == entry.id,
        OutputVatRegisterEntry.line_id == line.id,
    ))
    return {
        "organization_id": org_id,
        "source": source,
        "classification": {
            "tax_period": data.tax_period,
            "invoice_reference": data.invoice_reference,
            "tax_treatment": data.tax_treatment,
            "eschf_identifier": data.eschf_identifier,
            "eschf_status": data.eschf_status,
            "treatment_basis": data.treatment_basis,
            "export_evidence": data.export_evidence,
            "evidence": data.evidence,
        },
        "command": command,
        "digest": digest,
        "status": "already_registered" if existing else "reviewed_output_vat",
        "register_available": existing is None,
        "registered_id": existing.id if existing else None,
        "statutory_certified": False,
        "vat_treatment_verified": False,
    }


async def confirm_register(session, org_id: int, data: OutputVatRegisterConfirmInput, actor) -> OutputVatRegisterEntry:
    # Serialize request-key and source-line replay with the immutable insert.
    # Concurrent confirmations must return one receipt, not a unique-key error.
    await service.lock_organization(session, org_id)
    existing_request = await session.scalar(select(OutputVatRegisterEntry).where(
        OutputVatRegisterEntry.organization_id == org_id,
        OutputVatRegisterEntry.request_key == str(data.request_key),
    ))
    if existing_request is not None:
        if (existing_request.digest != data.digest or existing_request.entry_id != data.entry_id
                or existing_request.line_id != data.line_id):
            raise service.AccountingError("Register request key was reused with different content")
        return existing_request
    existing_line = await session.scalar(select(OutputVatRegisterEntry).where(
        OutputVatRegisterEntry.organization_id == org_id,
        OutputVatRegisterEntry.entry_id == data.entry_id,
        OutputVatRegisterEntry.line_id == data.line_id,
    ))
    if existing_line is not None:
        if existing_line.digest != data.digest:
            raise service.AccountingError("The source VAT line is already registered with different content")
        return existing_line
    prepared = await prepare_register(session, org_id, data)
    if prepared["digest"] != data.digest:
        raise service.AccountingError("Output-VAT register package changed; review it again")
    source = prepared["source"]
    row = OutputVatRegisterEntry(
        organization_id=org_id, request_key=str(data.request_key), entry_id=data.entry_id,
        line_id=data.line_id, source=source["source"], source_version=source["source_version"],
        entry_digest=source["entry_digest"], posting_date=date.fromisoformat(source["posting_date"]),
        tax_period=data.tax_period, amount=Decimal(source["amount"]), currency=source["currency"],
        side=source["side"], invoice_reference=data.invoice_reference,
        eschf_identifier=data.eschf_identifier, tax_treatment=data.tax_treatment,
        eschf_status=data.eschf_status, treatment_basis=data.treatment_basis,
        export_evidence=data.export_evidence, evidence=data.evidence,
        command=data.model_dump(mode="json"), digest=data.digest, actor=actor,
    )
    session.add(row)
    await session.flush()
    return row


async def register_result(session, org_id: int, request_key: UUID):
    return await session.scalar(select(OutputVatRegisterEntry).where(
        OutputVatRegisterEntry.organization_id == org_id,
        OutputVatRegisterEntry.request_key == str(request_key),
    ))


async def register_rows(session, org_id: int, start: date, end: date) -> dict:
    if end < start:
        raise service.AccountingError("End precedes start")
    rows = (await session.scalars(select(OutputVatRegisterEntry).where(
        OutputVatRegisterEntry.organization_id == org_id,
        OutputVatRegisterEntry.posting_date >= start,
        OutputVatRegisterEntry.posting_date <= end,
    ).order_by(OutputVatRegisterEntry.posting_date, OutputVatRegisterEntry.id))).all()
    totals: dict[str, Decimal] = {}
    for row in rows:
        totals[row.tax_treatment] = totals.get(row.tax_treatment, Decimal("0")) + row.amount
    return {
        "organization_id": org_id,
        "start": start,
        "end": end,
        "status": "review_register",
        "statutory_certified": False,
        "vat_treatment_verified": False,
        "rows": [serialize_row(row) for row in rows],
        "totals_by_treatment": {key: format(value, ".2f") for key, value in totals.items()},
    }
