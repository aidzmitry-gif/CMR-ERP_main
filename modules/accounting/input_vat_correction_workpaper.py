"""Append-only review-only bindings for VAT-only receipt correction drafts."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException
from pydantic import Field, field_validator
from sqlalchemy import or_, select
from starlette.concurrency import run_in_threadpool

from modules.accounting import inbound_vat_evidence
from modules.accounting.models import (
    Entry,
    InboundVatCorrectionWorkpaper,
    InboundVatEvidenceFile,
    Line,
    Period,
)
from modules.accounting.schemas import Input
from modules.accounting.service import AccountingError, lock_organization
from modules.procurement.receipt_documents import (
    ReceiptDocument,
    ReceiptPosting,
    ReceiptRevision,
    classify_receipt_correction,
    correction_document,
)

TAX_PERIOD = re.compile(r"^[0-9]{4}-(0[1-9]|1[0-2])$")
REVIEW_FLAGS = {
    "review_only": True,
    "signature_verified": False,
    "document_facts_verified": False,
    "deduction_eligibility_assessed": False,
    "accountant_accepted": False,
    "posting_available": False,
}


class InboundVatCorrectionWorkpaperInput(Input):
    receipt_id: int = Field(gt=0, strict=True)
    receipt_version: int = Field(gt=0, strict=True)
    tax_period: str = Field(pattern=r"^[0-9]{4}-(0[1-9]|1[0-2])$")


class InboundVatCorrectionWorkpaperConfirmInput(InboundVatCorrectionWorkpaperInput):
    request_key: UUID
    basis_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    reviewer_evidence: str = Field(min_length=10, max_length=2000)
    supersedes_workpaper_id: int | None = Field(default=None, gt=0, strict=True)

    @field_validator("reviewer_evidence")
    @classmethod
    def validate_reviewer_evidence(cls, value: str) -> str:
        if len(value.strip()) < 10 or "\x00" in value:
            raise ValueError("Reviewer evidence must contain meaningful text")
        return value


def _digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    ).encode()).hexdigest()


def _month(value: str) -> str:
    if not TAX_PERIOD.fullmatch(value):
        raise AccountingError("Tax period must use YYYY-MM")
    try:
        parsed = date.fromisoformat(value + "-01")
    except ValueError as exc:
        raise AccountingError("Tax period must use YYYY-MM") from exc
    if parsed.strftime("%Y-%m") != value:
        raise AccountingError("Tax period must use YYYY-MM")
    return value


def _is_account_18(code: str) -> bool:
    return code == "18" or code.startswith("18.")


def _line_snapshot(row: Line) -> dict:
    """Keep posted identity and amounts; the review intentionally omits side."""
    return {
        "line_id": row.id,
        "account_id": row.account_id,
        "account_code": row.account_code,
        "account_title": row.account_title,
        "category": row.category,
        "cash": row.cash,
        "amount": format(Decimal(row.amount), ".2f"),
        "currency": row.currency,
        "dimensions": row.dimensions or {},
    }


def _evidence_snapshot(item: dict) -> dict:
    return {
        "file_id": item["file_id"],
        "receipt_id": item["receipt_id"],
        "receipt_version": item["receipt_version"],
        "kind": item["kind"],
        "tax_period": item["tax_period"],
        "reference": item["reference"],
        "filename": item["filename"],
        "content_type": item["content_type"],
        "size_bytes": item["size_bytes"],
        "sha256": item["sha256"],
        "digest": item["digest"],
    }


async def _current_evidence(session, org_id: int, receipt_id: int,
                            receipt_version: int, tax_period: str) -> list[dict]:
    files: list[dict] = []
    for kind in ("supplier_eschf_xml", "supporting_document_pdf"):
        current = await inbound_vat_evidence.list_files(
            session, org_id, receipt_id, receipt_version, kind, current_only=True,
        )
        for item in current:
            if item["tax_period"] != tax_period:
                raise AccountingError(
                    "Current correction evidence uses a different tax period; review its evidence chain first"
                )
            files.append(_evidence_snapshot(item))
    return sorted(files, key=lambda item: (item["kind"], item["file_id"]))


async def _prepare(session, org_id: int, data: InboundVatCorrectionWorkpaperInput) -> dict:
    tax_period = _month(data.tax_period)
    await lock_organization(session, org_id)
    correction = await session.scalar(select(ReceiptDocument).where(
        ReceiptDocument.id == data.receipt_id,
        ReceiptDocument.organization_id == org_id,
    ).with_for_update())
    if correction is None:
        raise AccountingError("Receipt correction was not found in this organization")
    if (correction.status != "draft" or correction.current_version != data.receipt_version
            or correction.correction_of_receipt_id is None
            or correction.correction_of_version is None
            or correction.correction_of_entry_id is None
            or correction.correction_of_receipt_id == correction.id):
        raise AccountingError("Workpaper requires the exact current correction draft revision")
    if await session.get(ReceiptPosting, correction.id) is not None:
        raise AccountingError("A correction draft with a posting cannot receive a workpaper")

    original = await session.scalar(select(ReceiptDocument).where(
        ReceiptDocument.id == correction.correction_of_receipt_id,
        ReceiptDocument.organization_id == org_id,
    ).with_for_update())
    posting = await session.get(ReceiptPosting, correction.correction_of_receipt_id)
    entry = await session.scalar(select(Entry).where(
        Entry.id == correction.correction_of_entry_id,
        Entry.organization_id == org_id,
        Entry.source == f"procurement:receipt:{correction.correction_of_receipt_id}",
        Entry.source_version == correction.correction_of_version,
        Entry.operation == "inventory_purchase",
        Entry.correction_of.is_(None),
    ))
    original_revision = await session.scalar(select(ReceiptRevision).where(
        ReceiptRevision.receipt_id == correction.correction_of_receipt_id,
        ReceiptRevision.version == correction.correction_of_version,
    ))
    current_revision = await session.scalar(select(ReceiptRevision).where(
        ReceiptRevision.receipt_id == correction.id,
        ReceiptRevision.version == data.receipt_version,
    ))
    if (original is None or original.correction_of_receipt_id is not None or posting is None
            or original.current_version != correction.correction_of_version
            or posting.version != correction.correction_of_version
            or posting.entry_id != correction.correction_of_entry_id
            or entry is None or original_revision is None or current_revision is None):
        raise AccountingError("Correction source or exact source revisions are stale or inconsistent")

    original_document = correction_document(original_revision.document)
    corrected_document = correction_document(current_revision.document)
    flags, classification = classify_receipt_correction(original_document, corrected_document)
    if (not flags["vat_change"] or any(flags[name] for name in (
            "physical_change", "inventory_value_change", "primary_document_change",
            "operation_date_change"))):
        raise AccountingError("Workpaper is limited to VAT-only receipt corrections")

    if await session.scalar(select(Period.id).where(
            Period.organization_id == org_id,
            Period.month == tax_period,
            Period.closed.is_(True),
    )) is not None:
        raise AccountingError("Reopen the selected tax period before creating a workpaper")

    source_lines = (await session.scalars(select(Line).where(
        Line.entry_id == entry.id,
        or_(Line.account_code == "18", Line.account_code.like("18.%")),
    ).order_by(Line.id))).all()
    if not source_lines:
        raise AccountingError("Workpaper requires at least one account-18 source line")
    evidence_files = await _current_evidence(
        session, org_id, correction.id, data.receipt_version, tax_period,
    )
    if not evidence_files:
        raise AccountingError("Workpaper requires current correction evidence files")
    snapshot = {
        "organization_id": org_id,
        "receipt": {
            "correction_receipt_id": correction.id,
            "correction_version": data.receipt_version,
            "correction_revision_id": current_revision.id,
            "correction_document_digest": _digest(current_revision.document),
            "original_receipt_id": original.id,
            "original_version": correction.correction_of_version,
            "original_revision_id": original_revision.id,
            "original_document_digest": _digest(original_revision.document),
            "source_entry_id": entry.id,
            "source_entry": entry.source,
            "source_version": entry.source_version,
            "source_entry_digest": entry.digest,
            "source_posting_date": entry.posting_date.isoformat(),
            "source_operation_date": entry.operation_date.isoformat(),
        },
        "tax_period": tax_period,
        "classification": classification,
        "source_account_18_lines": [_line_snapshot(row) for row in source_lines],
        "evidence_files": evidence_files,
        **REVIEW_FLAGS,
    }
    basis_digest = _digest(snapshot)
    return {
        "organization_id": org_id,
        "receipt_id": correction.id,
        "receipt_version": data.receipt_version,
        "original_receipt_id": original.id,
        "original_version": correction.correction_of_version,
        "tax_period": tax_period,
        "basis": snapshot,
        "basis_digest": basis_digest,
        "status": "review_only_workpaper_ready",
        "source_account_18_line_count": len(source_lines),
        "current_evidence_file_count": len(evidence_files),
        **REVIEW_FLAGS,
        "evidence_bytes_verified_at_review": True,
    }


async def preview(session, org_id: int, data: InboundVatCorrectionWorkpaperInput) -> dict:
    return await _prepare(session, org_id, data)


def _result(row: InboundVatCorrectionWorkpaper) -> dict:
    if _digest(row.snapshot) != row.snapshot_digest or row.snapshot.get("organization_id") != row.organization_id:
        raise HTTPException(409, "Inbound VAT workpaper integrity requires reconciliation")
    receipt = row.snapshot.get("receipt")
    if (not isinstance(receipt, dict)
            or receipt.get("correction_receipt_id") != row.receipt_id
            or receipt.get("correction_version") != row.receipt_version
            or receipt.get("correction_revision_id") != row.correction_revision_id
            or receipt.get("original_receipt_id") != row.original_receipt_id
            or receipt.get("original_version") != row.original_version
            or receipt.get("original_revision_id") != row.original_revision_id
            or receipt.get("source_entry_id") != row.source_entry_id
            or receipt.get("source_entry_digest") != row.source_entry_digest
            or row.snapshot.get("tax_period") != row.tax_period
            or any(row.snapshot.get(key) is not value for key, value in REVIEW_FLAGS.items())):
        raise HTTPException(409, "Inbound VAT workpaper source scope requires reconciliation")
    for line in row.snapshot.get("source_account_18_lines", []):
        if not isinstance(line, dict) or any(key in line for key in ("side", "debit", "credit", "delta", "vat_delta")):
            raise HTTPException(409, "Inbound VAT workpaper contains prohibited direction or delta data")
    return {
        "workpaper_id": row.id,
        "organization_id": row.organization_id,
        "receipt_id": row.receipt_id,
        "receipt_version": row.receipt_version,
        "original_receipt_id": row.original_receipt_id,
        "original_version": row.original_version,
        "source_entry_id": row.source_entry_id,
        "source_entry_digest": row.source_entry_digest,
        "tax_period": row.tax_period,
        "revision": row.revision,
        "supersedes_workpaper_id": row.supersedes_id,
        "request_key": row.request_key,
        "request_digest": row.request_digest,
        "basis_digest": row.basis_digest,
        "snapshot_digest": row.snapshot_digest,
        "reviewer_evidence": row.reviewer_evidence,
        "reviewed_by": row.actor,
        "created_at": row.created_at,
        "snapshot": row.snapshot,
        "status": "review_only_workpaper",
        "evidence_bytes_verified_at_review": True,
        **REVIEW_FLAGS,
    }


async def _verify_snapshot_evidence(session, org_id: int, snapshot: dict) -> None:
    for evidence in snapshot.get("evidence_files", []):
        row = await session.scalar(select(InboundVatEvidenceFile).where(
            InboundVatEvidenceFile.id == evidence.get("file_id"),
            InboundVatEvidenceFile.organization_id == org_id,
            InboundVatEvidenceFile.receipt_id == evidence.get("receipt_id"),
            InboundVatEvidenceFile.receipt_version == evidence.get("receipt_version"),
            InboundVatEvidenceFile.kind == evidence.get("kind"),
            InboundVatEvidenceFile.tax_period == evidence.get("tax_period"),
            InboundVatEvidenceFile.digest == evidence.get("digest"),
            InboundVatEvidenceFile.sha256 == evidence.get("sha256"),
            InboundVatEvidenceFile.size_bytes == evidence.get("size_bytes"),
        ))
        if row is None:
            raise HTTPException(409, "Inbound VAT workpaper evidence file binding requires reconciliation")
        await run_in_threadpool(inbound_vat_evidence.verify_bytes, row)


async def _verify_snapshot_revisions(session, row: InboundVatCorrectionWorkpaper) -> None:
    receipt = row.snapshot.get("receipt") if isinstance(row.snapshot, dict) else None
    if not isinstance(receipt, dict):
        raise HTTPException(409, "Inbound VAT workpaper receipt revisions require reconciliation")
    correction_revision = await session.scalar(select(ReceiptRevision).where(
        ReceiptRevision.id == row.correction_revision_id,
        ReceiptRevision.receipt_id == row.receipt_id,
        ReceiptRevision.version == row.receipt_version,
    ).execution_options(populate_existing=True))
    original_revision = await session.scalar(select(ReceiptRevision).where(
        ReceiptRevision.id == row.original_revision_id,
        ReceiptRevision.receipt_id == row.original_receipt_id,
        ReceiptRevision.version == row.original_version,
    ).execution_options(populate_existing=True))
    if (correction_revision is None or original_revision is None
            or receipt.get("correction_document_digest") != _digest(correction_revision.document)
            or receipt.get("original_document_digest") != _digest(original_revision.document)):
        raise HTTPException(409, "Inbound VAT workpaper receipt revision documents require reconciliation")


async def create(session, org_id: int, data: InboundVatCorrectionWorkpaperConfirmInput,
                 actor: str) -> dict:
    await lock_organization(session, org_id)
    command = data.model_dump(mode="json")
    command["tax_period"] = _month(data.tax_period)
    command["reviewer_evidence"] = data.reviewer_evidence.strip()
    request_digest = _digest(command)
    existing = await session.scalar(select(InboundVatCorrectionWorkpaper).where(
        InboundVatCorrectionWorkpaper.organization_id == org_id,
        InboundVatCorrectionWorkpaper.request_key == str(data.request_key),
    ))
    if existing is not None:
        if existing.request_digest != request_digest:
            raise HTTPException(409, "Inbound VAT workpaper request key was reused with different content")
        await _verify_snapshot_evidence(session, org_id, existing.snapshot)
        await _verify_snapshot_revisions(session, existing)
        return _result(existing)

    prepared = await _prepare(session, org_id, InboundVatCorrectionWorkpaperInput(
        receipt_id=data.receipt_id,
        receipt_version=data.receipt_version,
        tax_period=data.tax_period,
    ))
    if prepared["basis_digest"] != data.basis_digest:
        raise AccountingError("Inbound VAT correction workpaper basis changed; review it again")

    latest = await session.scalar(select(InboundVatCorrectionWorkpaper).where(
        InboundVatCorrectionWorkpaper.organization_id == org_id,
        InboundVatCorrectionWorkpaper.receipt_id == data.receipt_id,
        InboundVatCorrectionWorkpaper.receipt_version == data.receipt_version,
        InboundVatCorrectionWorkpaper.tax_period == data.tax_period,
    ).order_by(InboundVatCorrectionWorkpaper.revision.desc()).limit(1).with_for_update())
    if latest is None:
        if data.supersedes_workpaper_id is not None:
            raise AccountingError("First inbound VAT workpaper cannot supersede another review")
        revision = 1
    else:
        if data.supersedes_workpaper_id != latest.id:
            raise AccountingError("Workpaper correction must supersede its latest same-scope revision")
        revision = latest.revision + 1

    snapshot = prepared["basis"]
    receipt = snapshot["receipt"]
    row = InboundVatCorrectionWorkpaper(
        organization_id=org_id,
        receipt_id=data.receipt_id,
        receipt_version=data.receipt_version,
        correction_revision_id=receipt["correction_revision_id"],
        original_receipt_id=receipt["original_receipt_id"],
        original_version=receipt["original_version"],
        original_revision_id=receipt["original_revision_id"],
        source_entry_id=receipt["source_entry_id"],
        source_entry_digest=receipt["source_entry_digest"],
        tax_period=data.tax_period,
        revision=revision,
        supersedes_id=data.supersedes_workpaper_id,
        request_key=str(data.request_key),
        request_digest=request_digest,
        basis_digest=prepared["basis_digest"],
        snapshot_digest=_digest(snapshot),
        snapshot=snapshot,
        reviewer_evidence=data.reviewer_evidence.strip(),
        actor=actor,
    )
    session.add(row)
    await session.flush()
    return _result(row)


async def by_request(session, org_id: int, request_key: UUID) -> dict:
    row = await session.scalar(select(InboundVatCorrectionWorkpaper).where(
        InboundVatCorrectionWorkpaper.organization_id == org_id,
        InboundVatCorrectionWorkpaper.request_key == str(request_key),
    ))
    if row is None:
        raise HTTPException(404, "Inbound VAT correction workpaper was not found")
    await _verify_snapshot_evidence(session, org_id, row.snapshot)
    await _verify_snapshot_revisions(session, row)
    return _result(row)


async def history(session, org_id: int, receipt_id: int, receipt_version: int,
                  tax_period: str) -> list[dict]:
    _month(tax_period)
    rows = (await session.scalars(select(InboundVatCorrectionWorkpaper).where(
        InboundVatCorrectionWorkpaper.organization_id == org_id,
        InboundVatCorrectionWorkpaper.receipt_id == receipt_id,
        InboundVatCorrectionWorkpaper.receipt_version == receipt_version,
        InboundVatCorrectionWorkpaper.tax_period == tax_period,
    ).order_by(InboundVatCorrectionWorkpaper.revision))).all()
    for row in rows:
        await _verify_snapshot_evidence(session, org_id, row.snapshot)
        await _verify_snapshot_revisions(session, row)
    return [_result(row) for row in rows]
