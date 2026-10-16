"""Private source files for VAT-only procurement receipt correction drafts."""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from typing import Literal
from urllib.parse import quote
from uuid import UUID

from fastapi import HTTPException
from pydantic import Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import aliased
from starlette.concurrency import run_in_threadpool

from core.services import intake_storage
from core.services.intake_storage import AttachmentRejected
from modules.accounting.models import (
    Entry,
    InboundVatEvidenceFile,
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

InboundVatEvidenceKind = Literal["supplier_eschf_xml", "supporting_document_pdf"]


class InboundVatEvidenceFileInput(Input):
    request_key: UUID
    receipt_id: int = Field(gt=0, strict=True)
    receipt_version: int = Field(gt=0, strict=True)
    kind: InboundVatEvidenceKind
    tax_period: str = Field(pattern=r"^[0-9]{4}-(0[1-9]|1[0-2])$")
    reference: str = Field(min_length=1, max_length=160)
    filename: str = Field(min_length=1, max_length=160)
    data_url: str = Field(min_length=20, max_length=intake_storage.MAX_B64_CHARS + 200)
    evidence: str = Field(min_length=10, max_length=2000)
    supersedes_id: int | None = Field(default=None, gt=0, strict=True)

    @model_validator(mode="after")
    def validate_filename(self):
        suffix = ".xml" if self.kind == "supplier_eschf_xml" else ".pdf"
        if (self.filename.lower().endswith(suffix) is False
                or any(char in self.filename for char in "/\\\r\n\x00")):
            raise ValueError("Filename must be a plain .xml or .pdf filename matching its evidence kind")
        return self


def _digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    ).encode()).hexdigest()


def _root() -> Path:
    configured = os.getenv("AIOS_ACCOUNTING_EVIDENCE_DATA_DIR")
    if not configured or not Path(configured).is_absolute():
        raise HTTPException(503, "Private accounting evidence storage is not configured")
    try:
        root = Path(configured).resolve(strict=True)
        if not root.is_dir():
            raise HTTPException(503, "Private accounting evidence storage is unavailable")
        if os.name != "nt" and stat.S_IMODE(root.stat().st_mode) & 0o077:
            raise HTTPException(503, "Private accounting evidence storage permissions are too broad")
    except (OSError, RuntimeError) as exc:
        raise HTTPException(503, "Private accounting evidence storage is unavailable") from exc
    return root


def _org_root(org_id: int, *, create: bool) -> Path:
    root = _root()
    path = root / str(org_id)
    if create:
        path.mkdir(mode=0o700 if os.name != "nt" else 0o777, exist_ok=True)
    if path.is_symlink():
        raise HTTPException(503, "Private accounting organization storage cannot be a symlink")
    if not path.is_dir():
        raise HTTPException(409, "Accounting evidence file is unavailable")
    if os.name != "nt" and stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise HTTPException(503, "Private accounting organization storage permissions are too broad")
    return path


def _decode(data: InboundVatEvidenceFileInput) -> tuple[str, bytes, str, str]:
    content_type, raw = intake_storage.decode_data_url(data.data_url)
    if not raw or len(raw) > intake_storage.MAX_SIZE_BYTES:
        raise AttachmentRejected("File is empty or exceeds the 10 MiB limit")
    if data.kind == "supporting_document_pdf":
        if content_type != "application/pdf" or not raw.startswith(b"%PDF-"):
            raise AttachmentRejected("Supporting evidence must be a PDF with a valid PDF signature")
        suffix = ".pdf"
    else:
        if content_type not in {"application/xml", "text/xml"}:
            raise AttachmentRejected("Supplier e-ЭСЧФ evidence must use an XML MIME type")
        # XML declarations are ASCII tokens even when the document uses UTF-16/32.
        # Remove encoding NULs before checking so a byte-level scan cannot be
        # bypassed with an alternate XML encoding.
        markup_tokens = raw.replace(b"\x00", b"")
        if re.search(rb"<!\s*(DOCTYPE|ENTITY)\b", markup_tokens, flags=re.IGNORECASE):
            raise AttachmentRejected("XML document type declarations are not accepted")
        try:
            ElementTree.fromstring(raw)
        except (ElementTree.ParseError, ValueError) as exc:
            raise AttachmentRejected("Supplier e-ЭСЧФ bytes are not well-formed XML") from exc
        suffix = ".xml"
    if not data.filename.lower().endswith(suffix):
        raise AttachmentRejected("File extension does not match its evidence kind")
    return content_type, raw, hashlib.sha256(raw).hexdigest(), suffix


def _metadata(row: InboundVatEvidenceFile) -> dict:
    return {
        "organization_id": row.organization_id,
        "receipt_id": row.receipt_id,
        "receipt_version": row.receipt_version,
        "kind": row.kind,
        "tax_period": row.tax_period,
        "reference": row.reference,
        "filename": row.filename,
        "content_type": row.content_type,
        "size_bytes": row.size_bytes,
        "sha256": row.sha256,
        "storage_filename": row.storage_filename,
        "evidence": row.evidence,
        "request_key": row.request_key,
        "supersedes_id": row.supersedes_id,
    }


def result(row: InboundVatEvidenceFile, *, is_current: bool = True) -> dict:
    metadata = _metadata(row)
    if (row.snapshot != metadata or _digest(metadata) != row.digest
            or _digest({key: value for key, value in metadata.items()
                        if key != "storage_filename"}) != row.request_digest):
        raise HTTPException(409, "Inbound VAT evidence metadata integrity requires reconciliation")
    return {
        "file_id": row.id,
        **{key: value for key, value in metadata.items() if key != "storage_filename"},
        "digest": row.digest,
        "actor": row.actor,
        "created_at": row.created_at,
        "is_current": is_current,
        "bytes_verified_at_upload": True,
        "signature_verified": False,
        "document_facts_verified": False,
        "posting_available": False,
    }


def verify_bytes(row: InboundVatEvidenceFile) -> bytes:
    result(row)
    try:
        org_root = _org_root(row.organization_id, create=False)
        path = intake_storage.resolve_path(org_root, row.storage_filename)
        if path.is_symlink():
            raise AttachmentRejected("Stored evidence file cannot be a symlink")
        raw = path.read_bytes()
        if len(raw) != row.size_bytes or hashlib.sha256(raw).hexdigest() != row.sha256:
            raise AttachmentRejected("Stored evidence bytes differ from their receipt")
        return raw
    except (AttachmentRejected, FileNotFoundError, OSError) as exc:
        raise HTTPException(409, "Inbound VAT evidence file is missing or differs from its receipt") from exc


async def _require_current_correction(session, org_id: int, data: InboundVatEvidenceFileInput):
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
        raise AccountingError("Evidence requires the exact current draft correction revision")
    if await session.get(ReceiptPosting, correction.id) is not None:
        raise AccountingError("A correction draft with a posting cannot receive evidence")

    original = await session.scalar(select(ReceiptDocument).where(
        ReceiptDocument.id == correction.correction_of_receipt_id,
        ReceiptDocument.organization_id == org_id,
    ).with_for_update())
    posting = await session.get(ReceiptPosting, correction.correction_of_receipt_id)
    if (original is None or original.correction_of_receipt_id is not None or posting is None
            or original.current_version != correction.correction_of_version
            or posting.version != correction.correction_of_version
            or posting.entry_id != correction.correction_of_entry_id):
        raise AccountingError("Correction source receipt identity is stale or inconsistent")

    entry = await session.scalar(select(Entry).where(
        Entry.id == correction.correction_of_entry_id,
        Entry.organization_id == org_id,
        Entry.source == f"procurement:receipt:{original.id}",
        Entry.source_version == correction.correction_of_version,
        Entry.operation == "inventory_purchase",
        Entry.correction_of.is_(None),
    ))
    original_revision = await session.scalar(select(ReceiptRevision).where(
        ReceiptRevision.receipt_id == original.id,
        ReceiptRevision.version == correction.correction_of_version,
    ))
    current_revision = await session.scalar(select(ReceiptRevision).where(
        ReceiptRevision.receipt_id == correction.id,
        ReceiptRevision.version == data.receipt_version,
    ))
    if entry is None or original_revision is None or current_revision is None:
        raise AccountingError("Correction source or exact current revision is missing")

    original_document = correction_document(original_revision.document)
    corrected_document = correction_document(current_revision.document)
    flags, _ = classify_receipt_correction(original_document, corrected_document)
    if (not flags["vat_change"]
            or any(flags[name] for name in (
                "physical_change", "inventory_value_change", "primary_document_change",
                "operation_date_change",
            ))):
        raise AccountingError("Evidence is limited to VAT-only receipt corrections")

    closed = await session.scalar(select(Period.id).where(
        Period.organization_id == org_id,
        Period.month == data.tax_period,
        Period.closed.is_(True),
    ))
    if closed is not None:
        raise AccountingError("Reopen the selected tax period before adding evidence")


async def _require_latest_supersedes(session, org_id: int, data: InboundVatEvidenceFileInput):
    if data.supersedes_id is None:
        existing = await session.scalar(select(InboundVatEvidenceFile.id).where(
            InboundVatEvidenceFile.organization_id == org_id,
            InboundVatEvidenceFile.receipt_id == data.receipt_id,
            InboundVatEvidenceFile.receipt_version == data.receipt_version,
            InboundVatEvidenceFile.kind == data.kind,
        ).limit(1))
        if existing is not None:
            raise AccountingError("Existing evidence must be superseded instead of starting a parallel chain")
        return
    previous = await session.scalar(select(InboundVatEvidenceFile).where(
        InboundVatEvidenceFile.id == data.supersedes_id,
        InboundVatEvidenceFile.organization_id == org_id,
        InboundVatEvidenceFile.receipt_id == data.receipt_id,
        InboundVatEvidenceFile.receipt_version == data.receipt_version,
        InboundVatEvidenceFile.kind == data.kind,
    ))
    if previous is None:
        raise AccountingError("Superseded evidence must be in the same organization, receipt revision and kind")
    successor = await session.scalar(select(InboundVatEvidenceFile.id).where(
        InboundVatEvidenceFile.supersedes_id == previous.id,
    ))
    if successor is not None:
        raise AccountingError("Only the latest evidence file can be superseded")


async def create(session, org_id: int, data: InboundVatEvidenceFileInput, actor: str) -> dict:
    await lock_organization(session, org_id)
    try:
        content_type, raw, sha256, suffix = await run_in_threadpool(_decode, data)
    except AttachmentRejected as exc:
        raise HTTPException(422, str(exc)) from exc

    storage_filename = data.request_key.hex + suffix
    metadata = {
        "organization_id": org_id,
        "receipt_id": data.receipt_id,
        "receipt_version": data.receipt_version,
        "kind": data.kind,
        "tax_period": data.tax_period,
        "reference": data.reference,
        "filename": data.filename,
        "content_type": content_type,
        "size_bytes": len(raw),
        "sha256": sha256,
        "storage_filename": storage_filename,
        "evidence": data.evidence,
        "request_key": str(data.request_key),
        "supersedes_id": data.supersedes_id,
    }
    request_digest = _digest({key: value for key, value in metadata.items() if key != "storage_filename"})
    existing = await session.scalar(select(InboundVatEvidenceFile).where(
        InboundVatEvidenceFile.organization_id == org_id,
        InboundVatEvidenceFile.request_key == str(data.request_key),
    ))
    if existing is not None:
        if existing.request_digest != request_digest:
            raise HTTPException(409, "Inbound VAT evidence request key was reused with different content")
        await run_in_threadpool(verify_bytes, existing)
        successor = await session.scalar(select(InboundVatEvidenceFile.id).where(
            InboundVatEvidenceFile.supersedes_id == existing.id,
        ))
        return result(existing, is_current=successor is None)

    await _require_current_correction(session, org_id, data)
    await _require_latest_supersedes(session, org_id, data)

    org_root = await run_in_threadpool(_org_root, org_id, create=True)
    await run_in_threadpool(intake_storage.durable_write, org_root, storage_filename, raw)
    try:
        await run_in_threadpool(intake_storage.verify_file, org_root, {
            "storage_path": storage_filename,
            "size_bytes": len(raw),
            "sha256": sha256,
        })
    except (AttachmentRejected, OSError) as exc:
        raise HTTPException(409, "Inbound VAT evidence bytes could not be verified after upload") from exc

    row = InboundVatEvidenceFile(
        **metadata,
        request_digest=request_digest,
        digest=_digest(metadata),
        snapshot=metadata,
        actor=actor,
    )
    session.add(row)
    await session.flush()
    return result(row)


async def list_files(session, org_id: int, receipt_id: int, receipt_version: int,
                     kind: InboundVatEvidenceKind, *, current_only: bool = False) -> list[dict]:
    scope = (
        InboundVatEvidenceFile.organization_id == org_id,
        InboundVatEvidenceFile.receipt_id == receipt_id,
        InboundVatEvidenceFile.receipt_version == receipt_version,
        InboundVatEvidenceFile.kind == kind,
    )
    query = select(InboundVatEvidenceFile).where(*scope).order_by(InboundVatEvidenceFile.id)
    if current_only:
        successor = aliased(InboundVatEvidenceFile)
        query = query.where(~select(successor.id).where(
            successor.supersedes_id == InboundVatEvidenceFile.id,
        ).exists())
    rows = (await session.scalars(query)).all()
    if not current_only:
        superseded = {row.supersedes_id for row in rows if row.supersedes_id is not None}
        for row in rows:
            await run_in_threadpool(verify_bytes, row)
        return [result(row, is_current=row.id not in superseded) for row in rows]
    for row in rows:
        await run_in_threadpool(verify_bytes, row)
    return [result(row) for row in rows]


async def file_for(session, org_id: int, file_id: int, receipt_id: int,
                   receipt_version: int, kind: InboundVatEvidenceKind) -> InboundVatEvidenceFile:
    row = await session.scalar(select(InboundVatEvidenceFile).where(
        InboundVatEvidenceFile.id == file_id,
        InboundVatEvidenceFile.organization_id == org_id,
        InboundVatEvidenceFile.receipt_id == receipt_id,
        InboundVatEvidenceFile.receipt_version == receipt_version,
        InboundVatEvidenceFile.kind == kind,
    ))
    if row is None:
        raise AccountingError("Evidence file does not belong to this receipt revision and kind")
    return row


def download_filename(row: InboundVatEvidenceFile) -> str:
    return "attachment; filename*=UTF-8''" + quote(row.filename, safe="")
