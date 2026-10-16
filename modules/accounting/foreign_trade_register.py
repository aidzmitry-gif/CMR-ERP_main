"""Explicit evidence register for import/export accounting sources.

The register records the accountant's reviewed trade lane and documents for
one already-posted ledger line.  It deliberately does not calculate customs,
VAT, landed cost or a declaration: those values must be supplied explicitly
and remain non-statutory until the applicable policy and period are accepted.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator
from sqlalchemy import and_, or_, select

from modules.accounting import service
from modules.accounting.models import Entry, ForeignTradeRegisterEntry, Line, Period
from modules.accounting.schemas import Input, Money, Quantity

TradeMode = Literal["eaeu_import", "third_country_import", "export"]


class ForeignTradeRegisterInput(Input):
    request_key: UUID
    entry_id: int = Field(gt=0, strict=True)
    line_id: int = Field(gt=0, strict=True)
    expected_entry_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    tax_period: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    trade_mode: TradeMode
    partner_country: str = Field(min_length=2, max_length=64)
    contract_reference: str = Field(min_length=1, max_length=200)
    invoice_reference: str = Field(min_length=1, max_length=200)
    customs_reference: str | None = Field(default=None, max_length=200)
    eaeu_reference: str | None = Field(default=None, max_length=200)
    incoterms: str | None = Field(default=None, max_length=16)
    original_amount: Money | None = None
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    rate: Quantity | None = None
    rate_scale: int | None = Field(default=None, gt=0, le=2147483647)
    rate_date: date | None = None
    rate_source: str | None = Field(default=None, max_length=200)
    customs_duty: Money = Field(default=Decimal("0"))
    import_vat: Money = Field(default=Decimal("0"))
    export_evidence: str | None = Field(default=None, max_length=2000)
    evidence: str = Field(min_length=10, max_length=2000)

    @model_validator(mode="after")
    def validate_explicit_trade_evidence(self):
        if self.trade_mode in {"eaeu_import", "third_country_import"} and not self.incoterms:
            raise ValueError("Import trade evidence requires explicit Incoterms")
        if self.trade_mode == "eaeu_import" and not self.eaeu_reference:
            raise ValueError("EAEU import requires an explicit accompanying document reference")
        if self.trade_mode in {"third_country_import", "export"} and not self.customs_reference:
            raise ValueError("This trade lane requires an explicit customs declaration reference")
        if self.trade_mode == "export" and not self.export_evidence:
            raise ValueError("Export requires explicit transport/customs evidence")
        if self.trade_mode == "export" and (self.customs_duty or self.import_vat):
            raise ValueError("Import duty and import VAT are not valid for an export lane")
        fx_values = (self.original_amount, self.rate, self.rate_scale, self.rate_date, self.rate_source)
        if self.currency == "BYN":
            if any(value is not None for value in fx_values):
                raise ValueError("BYN trade evidence must not carry foreign-exchange metadata")
        elif any(value is None for value in fx_values) or not self.rate_source:
            raise ValueError("Foreign-currency trade evidence needs amount, rate, scale, date and source")
        return self


class ForeignTradeRegisterConfirmInput(ForeignTradeRegisterInput):
    digest: str = Field(pattern=r"^[a-f0-9]{64}$")


def _period(value: str) -> str:
    try:
        parsed = date.fromisoformat(value + "-01")
    except ValueError as exc:
        raise service.AccountingError("Trade tax period must be YYYY-MM") from exc
    if parsed.strftime("%Y-%m") != value:
        raise service.AccountingError("Trade tax period must be YYYY-MM")
    return value


def _digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()


def _is_import_account(code: str) -> bool:
    return code == "10" or code.startswith("10.") or code == "18" or code.startswith("18.") \
        or code == "20" or code.startswith("20.") or code == "41" or code.startswith("41.")


def _is_export_account(code: str) -> bool:
    return code == "90.1" or code.startswith("90.1.")


def serialize_row(row: ForeignTradeRegisterEntry) -> dict:
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
        "trade_mode": row.trade_mode,
        "partner_country": row.partner_country,
        "contract_reference": row.contract_reference,
        "invoice_reference": row.invoice_reference,
        "customs_reference": row.customs_reference,
        "eaeu_reference": row.eaeu_reference,
        "incoterms": row.incoterms,
        "amount": format(row.amount, ".2f"),
        "currency": row.currency,
        "original_amount": format(row.original_amount, ".2f") if row.original_amount is not None else None,
        "rate": format(row.rate, ".6f") if row.rate is not None else None,
        "rate_scale": row.rate_scale,
        "rate_date": row.rate_date,
        "rate_source": row.rate_source,
        "customs_duty": format(row.customs_duty, ".2f"),
        "import_vat": format(row.import_vat, ".2f"),
        "export_evidence": row.export_evidence,
        "evidence": row.evidence,
        "command": row.command,
        "digest": row.digest,
        "actor": row.actor,
        "created_at": row.created_at,
        "statutory_certified": False,
        "trade_treatment_verified": False,
    }


async def _source(session, org_id: int, data: ForeignTradeRegisterInput):
    _period(data.tax_period)
    entry = await session.scalar(select(Entry).where(
        Entry.organization_id == org_id, Entry.id == data.entry_id,
    ))
    line = await session.scalar(select(Line).where(
        Line.id == data.line_id, Line.entry_id == data.entry_id,
    ))
    if entry is None or line is None:
        raise service.AccountingError("Foreign-trade source line was not found in this organization")
    if entry.digest != data.expected_entry_digest:
        raise service.AccountingError("The trade source posting changed; read it again")
    if line.currency != data.currency:
        raise service.AccountingError("Trade currency must match the posted source line")
    if data.trade_mode == "export":
        if line.side != "credit" or not _is_export_account(line.account_code):
            raise service.AccountingError("Export evidence must bind to a credit 90.1 source line")
    elif line.side != "debit" or not _is_import_account(line.account_code):
        raise service.AccountingError("Import evidence must bind to a debit inventory or input-VAT source line")
    if data.currency == "BYN":
        if any(value is not None for value in (line.original_amount, line.rate, line.rate_scale, line.rate_date, line.rate_source)):
            raise service.AccountingError("The BYN source line unexpectedly contains foreign-exchange metadata")
    else:
        if (line.original_amount != data.original_amount or line.rate != data.rate
                or line.rate_scale != data.rate_scale or line.rate_date != data.rate_date
                or line.rate_source != data.rate_source):
            raise service.AccountingError("Trade rate evidence does not match the posted source line")
    closed = await session.scalar(select(Period.id).where(
        Period.organization_id == org_id, Period.month == data.tax_period, Period.closed.is_(True),
    ))
    if closed is not None:
        raise service.AccountingError("Reopen the tax period before adding a trade register classification")
    return entry, line


def _source_snapshot(entry: Entry, line: Line) -> dict:
    return {
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
        "original_amount": format(line.original_amount, ".2f") if line.original_amount is not None else None,
        "rate": format(line.rate, ".6f") if line.rate is not None else None,
        "rate_scale": line.rate_scale,
        "rate_date": line.rate_date.isoformat() if line.rate_date else None,
        "rate_source": line.rate_source,
        "account_code": line.account_code,
    }


async def prepare_register(session, org_id: int, data: ForeignTradeRegisterInput) -> dict:
    entry, line = await _source(session, org_id, data)
    command = data.model_dump(mode="json", exclude={"digest"})
    source = _source_snapshot(entry, line)
    digest = _digest({"command": command, "source": source})
    existing = await session.scalar(select(ForeignTradeRegisterEntry).where(
        ForeignTradeRegisterEntry.organization_id == org_id,
        ForeignTradeRegisterEntry.entry_id == entry.id,
        ForeignTradeRegisterEntry.line_id == line.id,
    ))
    return {
        "organization_id": org_id,
        "source": source,
        "classification": {key: command[key] for key in (
            "tax_period", "trade_mode", "partner_country", "contract_reference", "invoice_reference",
            "customs_reference", "eaeu_reference", "incoterms", "currency", "customs_duty", "import_vat",
            "export_evidence", "evidence",
        )},
        "command": command,
        "digest": digest,
        "status": "already_registered" if existing else "reviewed_foreign_trade",
        "register_available": existing is None,
        "registered_id": existing.id if existing else None,
        "statutory_certified": False,
        "trade_treatment_verified": False,
    }


async def confirm_register(session, org_id: int, data: ForeignTradeRegisterConfirmInput, actor) -> ForeignTradeRegisterEntry:
    # Serialize request-key/source-line replay with the immutable insert.
    await service.lock_organization(session, org_id)
    existing_request = await session.scalar(select(ForeignTradeRegisterEntry).where(
        ForeignTradeRegisterEntry.organization_id == org_id,
        ForeignTradeRegisterEntry.request_key == str(data.request_key),
    ))
    if existing_request is not None:
        if (existing_request.digest != data.digest or existing_request.entry_id != data.entry_id
                or existing_request.line_id != data.line_id):
            raise service.AccountingError("Trade register request key was reused with different content")
        return existing_request
    existing_line = await session.scalar(select(ForeignTradeRegisterEntry).where(
        ForeignTradeRegisterEntry.organization_id == org_id,
        ForeignTradeRegisterEntry.entry_id == data.entry_id,
        ForeignTradeRegisterEntry.line_id == data.line_id,
    ))
    if existing_line is not None:
        if existing_line.digest != data.digest:
            raise service.AccountingError("The source trade line is already registered with different content")
        return existing_line
    prepared = await prepare_register(session, org_id, data)
    if prepared["digest"] != data.digest:
        raise service.AccountingError("Foreign-trade register package changed; review it again")
    source = prepared["source"]
    row = ForeignTradeRegisterEntry(
        organization_id=org_id, request_key=str(data.request_key), entry_id=data.entry_id,
        line_id=data.line_id, source=source["source"], source_version=source["source_version"],
        entry_digest=source["entry_digest"], posting_date=date.fromisoformat(source["posting_date"]),
        tax_period=data.tax_period, trade_mode=data.trade_mode, partner_country=data.partner_country,
        contract_reference=data.contract_reference, invoice_reference=data.invoice_reference,
        customs_reference=data.customs_reference, eaeu_reference=data.eaeu_reference,
        incoterms=data.incoterms, amount=Decimal(source["amount"]), currency=source["currency"],
        original_amount=data.original_amount, rate=data.rate, rate_scale=data.rate_scale,
        rate_date=data.rate_date, rate_source=data.rate_source, customs_duty=data.customs_duty,
        import_vat=data.import_vat, export_evidence=data.export_evidence, evidence=data.evidence,
        command=data.model_dump(mode="json"), digest=data.digest, actor=actor,
    )
    session.add(row)
    await session.flush()
    return row


async def register_result(session, org_id: int, request_key: UUID):
    return await session.scalar(select(ForeignTradeRegisterEntry).where(
        ForeignTradeRegisterEntry.organization_id == org_id,
        ForeignTradeRegisterEntry.request_key == str(request_key),
    ))


async def worksheet(session, org_id: int, start: date, end: date) -> dict:
    """Return possible trade source lines without guessing their trade lane."""
    if end < start:
        raise service.AccountingError("End precedes start")
    await service.lock_organization(session, org_id)
    records = (await session.execute(select(Entry, Line).join(
        Line, Line.entry_id == Entry.id,
    ).where(
        Entry.organization_id == org_id,
        Entry.posting_date >= start,
        Entry.posting_date <= end,
        or_(and_(Line.side == "credit", or_(Line.account_code == "90.1", Line.account_code.like("90.1.%"))),
            and_(Line.side == "debit", or_(Line.account_code == "41", Line.account_code.like("41.%"),
                                            Line.account_code == "18", Line.account_code.like("18.%"),
                                            Line.account_code == "10", Line.account_code.like("10.%"),
                                            Line.account_code == "20", Line.account_code.like("20.%")))),
    ).order_by(Entry.posting_date, Entry.id, Line.id))).all()
    line_ids = [line.id for _, line in records]
    registered = {}
    if line_ids:
        rows = (await session.scalars(select(ForeignTradeRegisterEntry).where(
            ForeignTradeRegisterEntry.organization_id == org_id,
            ForeignTradeRegisterEntry.line_id.in_(line_ids),
        ))).all()
        registered = {row.line_id: row for row in rows}
    rows = []
    for entry, line in records:
        register = registered.get(line.id)
        issues = []
        if line.currency != "BYN" and any(value is None for value in (
                line.original_amount, line.rate, line.rate_scale, line.rate_date, line.rate_source)):
            issues.append("foreign_currency_rate_evidence_missing")
        rows.append({
            "entry_id": entry.id, "line_id": line.id, "source": entry.source,
            "source_version": entry.source_version, "operation": entry.operation,
            "posting_date": entry.posting_date, "document_date": entry.document_date,
            "operation_date": entry.operation_date, "side": line.side,
            "amount": format(line.amount, ".2f"), "currency": line.currency,
            "original_amount": format(line.original_amount, ".2f") if line.original_amount is not None else None,
            "rate": format(line.rate, ".6f") if line.rate is not None else None,
            "rate_scale": line.rate_scale, "rate_date": line.rate_date,
            "rate_source": line.rate_source, "account_code": line.account_code,
            "account_title": line.account_title, "dimensions": line.dimensions or {},
            "review_issues": issues, "trade_mode": register.trade_mode if register else "not_assessed",
            "register_id": register.id if register else None,
            "register_tax_period": register.tax_period if register else None,
            "entry_digest": entry.digest, "registered": register is not None,
        })
    return {
        "organization_id": org_id, "start": start, "end": end,
        "status": "review_worksheet", "statutory_certified": False,
        "trade_treatment_verified": False, "rows": rows,
        "rows_needing_metadata_review": sum(bool(row["review_issues"]) for row in rows),
        "rows_needing_register_review": sum(not row["registered"] for row in rows),
    }


async def register_rows(session, org_id: int, start: date, end: date) -> dict:
    if end < start:
        raise service.AccountingError("End precedes start")
    rows = (await session.scalars(select(ForeignTradeRegisterEntry).where(
        ForeignTradeRegisterEntry.organization_id == org_id,
        ForeignTradeRegisterEntry.posting_date >= start,
        ForeignTradeRegisterEntry.posting_date <= end,
    ).order_by(ForeignTradeRegisterEntry.posting_date, ForeignTradeRegisterEntry.id))).all()
    totals: dict[str, Decimal] = {}
    for row in rows:
        totals[row.trade_mode] = totals.get(row.trade_mode, Decimal("0")) + row.amount
    return {
        "organization_id": org_id, "start": start, "end": end,
        "status": "review_register", "statutory_certified": False,
        "trade_treatment_verified": False, "rows": [serialize_row(row) for row in rows],
        "totals_by_trade_mode": {key: format(value, ".2f") for key, value in totals.items()},
    }
