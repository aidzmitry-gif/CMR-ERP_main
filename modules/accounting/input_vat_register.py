"""Explicit input-VAT register evidence.

This is deliberately a register workflow, not a deduction engine.  An
accountant records the tax period, invoice/ESCHF evidence and the reviewed
classification for one already posted account-18 line.  The workflow never
creates a tax deduction, changes the ledger or infers a result from payment.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator
from sqlalchemy import select

from modules.accounting import service
from modules.accounting.models import Entry, InputVatRegisterEntry, Line, Period
from modules.accounting.schemas import Input


class InputVatRegisterInput(Input):
    request_key: UUID
    entry_id: int = Field(gt=0, strict=True)
    line_id: int = Field(gt=0, strict=True)
    expected_entry_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    tax_period: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    invoice_reference: str = Field(min_length=1, max_length=200)
    eschf_identifier: str | None = Field(default=None, max_length=200)
    deduction_status: Literal["not_assessed", "pending", "eligible", "not_eligible"]
    eschf_status: Literal["not_provided", "provided", "not_required", "pending"]
    right_basis: str = Field(min_length=10, max_length=2000)
    evidence: str = Field(min_length=10, max_length=2000)

    @model_validator(mode="after")
    def validate_explicit_evidence(self):
        if self.eschf_status == "provided" and not self.eschf_identifier:
            raise ValueError("ЭСЧФ identifier is required when the document is provided")
        if self.eschf_status != "provided" and self.eschf_identifier:
            raise ValueError("ЭСЧФ identifier requires the provided document status")
        if self.deduction_status == "eligible" and self.eschf_status not in {"provided", "not_required"}:
            raise ValueError("Eligible VAT requires an explicit ЭСЧФ status and evidence")
        return self


class InputVatRegisterConfirmInput(InputVatRegisterInput):
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


def serialize_row(row: InputVatRegisterEntry) -> dict:
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
        "deduction_status": row.deduction_status,
        "eschf_status": row.eschf_status,
        "right_basis": row.right_basis,
        "evidence": row.evidence,
        "command": row.command,
        "digest": row.digest,
        "actor": row.actor,
        "created_at": row.created_at,
        "statutory_certified": False,
    }


async def _source(session, org_id: int, data: InputVatRegisterInput):
    _period(data.tax_period)
    entry = await session.scalar(select(Entry).where(
        Entry.organization_id == org_id, Entry.id == data.entry_id,
    ))
    line = await session.scalar(select(Line).where(
        Line.id == data.line_id, Line.entry_id == data.entry_id,
    ))
    if entry is None or line is None:
        raise service.AccountingError("Input-VAT source line was not found in this organization")
    if entry.digest != data.expected_entry_digest:
        raise service.AccountingError("The source posting changed; read it again")
    if not line.account_code == "18" and not line.account_code.startswith("18."):
        raise service.AccountingError("The selected source line is not an input-VAT account")
    if line.amount <= Decimal("0"):
        raise service.AccountingError("Input-VAT source amount must be positive")
    if line.side == "credit" and data.deduction_status == "eligible":
        raise service.AccountingError("A credit/reversal VAT line cannot be marked eligible")
    if data.eschf_status == "provided" and not data.eschf_identifier:
        raise service.AccountingError("ЭСЧФ identifier is required when the document is provided")
    closed = await session.scalar(select(Period.id).where(
        Period.organization_id == org_id, Period.month == data.tax_period, Period.closed.is_(True),
    ))
    if closed is not None:
        raise service.AccountingError("Reopen the tax period before adding a register classification")
    return entry, line


async def prepare_register(session, org_id: int, data: InputVatRegisterInput) -> dict:
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
    existing = await session.scalar(select(InputVatRegisterEntry).where(
        InputVatRegisterEntry.organization_id == org_id,
        InputVatRegisterEntry.entry_id == entry.id,
        InputVatRegisterEntry.line_id == line.id,
    ))
    return {
        "organization_id": org_id,
        "source": source,
        "classification": {
            "tax_period": data.tax_period,
            "invoice_reference": data.invoice_reference,
            "eschf_identifier": data.eschf_identifier,
            "deduction_status": data.deduction_status,
            "eschf_status": data.eschf_status,
            "right_basis": data.right_basis,
            "evidence": data.evidence,
        },
        "command": command,
        "digest": digest,
        "status": "already_registered" if existing else "reviewed_input_vat",
        "register_available": existing is None,
        "registered_id": existing.id if existing else None,
        "statutory_certified": False,
        "deduction_assessed": False,
    }


async def confirm_register(session, org_id: int, data: InputVatRegisterConfirmInput, actor) -> InputVatRegisterEntry:
    # Serialize request-key and source-line replay with the immutable insert.
    # Concurrent confirmations must return one receipt, not a unique-key error.
    await service.lock_organization(session, org_id)
    # Read the immutable receipt first so an exact retry remains readable even
    # after the tax period was subsequently closed.
    existing_request = await session.scalar(select(InputVatRegisterEntry).where(
        InputVatRegisterEntry.organization_id == org_id,
        InputVatRegisterEntry.request_key == str(data.request_key),
    ))
    if existing_request is not None:
        if (existing_request.digest != data.digest or existing_request.entry_id != data.entry_id
                or existing_request.line_id != data.line_id):
            raise service.AccountingError("Register request key was reused with different content")
        return existing_request
    existing_line = await session.scalar(select(InputVatRegisterEntry).where(
        InputVatRegisterEntry.organization_id == org_id,
        InputVatRegisterEntry.entry_id == data.entry_id,
        InputVatRegisterEntry.line_id == data.line_id,
    ))
    if existing_line is not None:
        if existing_line.digest != data.digest:
            raise service.AccountingError("The source VAT line is already registered with different content")
        return existing_line
    prepared = await prepare_register(session, org_id, data)
    if prepared["digest"] != data.digest:
        raise service.AccountingError("Input-VAT register package changed; review it again")
    source = prepared["source"]
    row = InputVatRegisterEntry(
        organization_id=org_id, request_key=str(data.request_key), entry_id=data.entry_id,
        line_id=data.line_id, source=source["source"], source_version=source["source_version"],
        entry_digest=source["entry_digest"], posting_date=date.fromisoformat(source["posting_date"]),
        tax_period=data.tax_period, amount=Decimal(source["amount"]), currency=source["currency"],
        side=source["side"], invoice_reference=data.invoice_reference,
        eschf_identifier=data.eschf_identifier, deduction_status=data.deduction_status,
        eschf_status=data.eschf_status, right_basis=data.right_basis, evidence=data.evidence,
        command=data.model_dump(mode="json"), digest=data.digest, actor=actor,
    )
    session.add(row)
    await session.flush()
    return row


async def register_result(session, org_id: int, request_key: UUID):
    return await session.scalar(select(InputVatRegisterEntry).where(
        InputVatRegisterEntry.organization_id == org_id,
        InputVatRegisterEntry.request_key == str(request_key),
    ))


async def register_rows(session, org_id: int, start: date, end: date) -> dict:
    if end < start:
        raise service.AccountingError("End precedes start")
    rows = (await session.scalars(select(InputVatRegisterEntry).where(
        InputVatRegisterEntry.organization_id == org_id,
        InputVatRegisterEntry.posting_date >= start,
        InputVatRegisterEntry.posting_date <= end,
    ).order_by(InputVatRegisterEntry.posting_date, InputVatRegisterEntry.id))).all()
    totals: dict[str, Decimal] = {}
    for row in rows:
        totals[row.deduction_status] = totals.get(row.deduction_status, Decimal("0")) + row.amount
    return {
        "organization_id": org_id,
        "start": start,
        "end": end,
        "status": "review_register",
        "statutory_certified": False,
        "deduction_assessed": False,
        "rows": [serialize_row(row) for row in rows],
        "totals_by_status": {key: format(value, ".2f") for key, value in totals.items()},
    }
