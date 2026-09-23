"""Private, organization-owned source files for payroll; no remote fetching."""
from __future__ import annotations

import hashlib
import json
import os
import stat
from datetime import date
from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import Field, model_validator
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from core.services import intake_storage
from core.services.intake_storage import AttachmentRejected
from modules.accounting.models import PayrollEmploymentBinding, PayrollEvidenceFile
from modules.accounting.schemas import Input
from modules.accounting.service import AccountingError, lock_organization


class PayrollEvidenceFileInput(Input):
    request_key: UUID
    kind: Literal["employment_contract", "timesheet", "payroll_policy", "base_adjustment"]
    employment_binding_id: int | None = Field(default=None, gt=0, strict=True)
    month: str | None = Field(default=None, pattern=r"^[0-9]{4}-(0[1-9]|1[0-2])$")
    reference: str = Field(min_length=1, max_length=160)
    filename: str = Field(min_length=1, max_length=160)
    data_url: str = Field(min_length=20, max_length=intake_storage.MAX_B64_CHARS + 200)
    evidence: str = Field(min_length=10, max_length=2000)

    @model_validator(mode="after")
    def check_scope(self):
        if self.kind == "payroll_policy":
            if self.employment_binding_id is not None or self.month is not None:
                raise ValueError("Policy file is organization-scoped, not employee-scoped")
        elif self.kind == "employment_contract":
            if self.employment_binding_id is None or self.month is not None:
                raise ValueError("Contract file needs an employee binding and no month")
        elif self.employment_binding_id is None or self.month is None:
            raise ValueError("Timesheet or adjustment needs an employee binding and month")
        if self.month is not None:
            try:
                parsed = date.fromisoformat(self.month + "-01")
            except ValueError as exc:
                raise ValueError("Month must be YYYY-MM") from exc
            if parsed.strftime("%Y-%m") != self.month:
                raise ValueError("Month must be YYYY-MM")
        return self


def _digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    ).encode()).hexdigest()


def _root() -> Path:
    configured = os.getenv("AIOS_PAYROLL_DATA_DIR")
    if not configured or not Path(configured).is_absolute():
        raise HTTPException(503, "Private payroll file storage is not configured")
    try:
        root = Path(configured).resolve(strict=True)
        if not root.is_dir():
            raise HTTPException(503, "Private payroll file storage is unavailable")
        if os.name != "nt" and stat.S_IMODE(root.stat().st_mode) & 0o077:
            raise HTTPException(503, "Private payroll file storage permissions are too broad")
    except (OSError, RuntimeError) as exc:
        raise HTTPException(503, "Private payroll file storage is unavailable") from exc
    return root


def _org_root(org_id: int, *, create: bool) -> Path:
    root = _root()
    path = root / str(org_id)
    if create:
        # Python 3.12 applies restrictive Windows ACLs for mode=0700; the
        # service account can then lose access to its own newly made folder.
        # POSIX keeps the explicit private mode, Windows inherits root ACLs.
        path.mkdir(mode=0o700 if os.name != "nt" else 0o777, exist_ok=True)
    if path.is_symlink():
        raise HTTPException(503, "Private payroll organization storage cannot be a symlink")
    if not path.is_dir():
        raise HTTPException(409, "Payroll source file is unavailable")
    if os.name != "nt" and stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise HTTPException(503, "Private payroll organization storage permissions are too broad")
    return path


def _decode(data_url: str) -> tuple[str, bytes, str]:
    content_type, raw = intake_storage.decode_data_url(data_url)
    intake_storage.validate_attachment(content_type, raw)
    signatures = {
        "application/pdf": b"%PDF-",
        "image/jpeg": b"\xff\xd8\xff",
        "image/png": b"\x89PNG\r\n\x1a\n",
        "application/msword": b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": b"PK\x03\x04",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": b"PK\x03\x04",
    }
    if not raw.startswith(signatures[content_type]):
        raise AttachmentRejected("File bytes do not match the declared document type")
    return content_type, raw, hashlib.sha256(raw).hexdigest()


def _metadata(row: PayrollEvidenceFile) -> dict:
    return {
        "organization_id": row.organization_id,
        "employment_binding_id": row.employment_binding_id,
        "kind": row.kind,
        "month": row.month,
        "reference": row.reference,
        "filename": row.filename,
        "content_type": row.content_type,
        "size_bytes": row.size_bytes,
        "sha256": row.sha256,
        "storage_filename": row.storage_filename,
        "evidence": row.evidence,
        "request_key": row.request_key,
    }


def result(row: PayrollEvidenceFile) -> dict:
    metadata = _metadata(row)
    if row.snapshot != metadata or _digest(metadata) != row.digest:
        raise HTTPException(409, "Payroll source file metadata integrity requires reconciliation")
    return {
        "file_id": row.id,
        **{key: value for key, value in metadata.items() if key != "storage_filename"},
        "digest": row.digest,
        "actor": row.actor,
        "bytes_verified_at_upload": True,
        "document_facts_verified": False,
    }


def verify_bytes(row: PayrollEvidenceFile) -> bytes:
    result(row)
    try:
        org_root = _org_root(row.organization_id, create=False)
        intake_storage.verify_file(org_root, {
            "storage_path": row.storage_filename,
            "size_bytes": row.size_bytes,
            "sha256": row.sha256,
        })
        return intake_storage.resolve_path(org_root, row.storage_filename).read_bytes()
    except (AttachmentRejected, FileNotFoundError, OSError) as exc:
        raise HTTPException(409, "Payroll source file is missing or differs from its receipt") from exc


async def create(session, org_id: int, data: PayrollEvidenceFileInput, actor: str) -> dict:
    await lock_organization(session, org_id)
    try:
        content_type, raw, sha256 = await run_in_threadpool(_decode, data.data_url)
    except AttachmentRejected as exc:
        raise HTTPException(422, str(exc)) from exc
    metadata = {
        "organization_id": org_id,
        "employment_binding_id": data.employment_binding_id,
        "kind": data.kind,
        "month": data.month,
        "reference": data.reference,
        "filename": data.filename,
        "content_type": content_type,
        "size_bytes": len(raw),
        "sha256": sha256,
        "storage_filename": data.request_key.hex + intake_storage.ALLOWED_CONTENT_TYPES[content_type],
        "evidence": data.evidence,
        "request_key": str(data.request_key),
    }
    request_digest = _digest({key: value for key, value in metadata.items()
                              if key != "storage_filename"})
    existing = await session.scalar(select(PayrollEvidenceFile).where(
        PayrollEvidenceFile.organization_id == org_id,
        PayrollEvidenceFile.request_key == str(data.request_key),
    ))
    if existing is not None:
        if existing.request_digest != request_digest:
            raise HTTPException(409, "Payroll file request key was reused with different content")
        await run_in_threadpool(verify_bytes, existing)
        return result(existing)

    if data.employment_binding_id is not None:
        binding = await session.scalar(select(PayrollEmploymentBinding).where(
            PayrollEmploymentBinding.id == data.employment_binding_id,
            PayrollEmploymentBinding.organization_id == org_id,
        ))
        if binding is None:
            raise AccountingError("Payroll source file needs this organization's employment binding")
        if data.kind == "employment_contract" and data.reference != binding.source_document:
            raise AccountingError("Contract file reference must match the employment binding")
    org_root = await run_in_threadpool(_org_root, org_id, create=True)
    await run_in_threadpool(intake_storage.durable_write, org_root, metadata["storage_filename"], raw)
    try:
        await run_in_threadpool(intake_storage.verify_file, org_root, {
            "storage_path": metadata["storage_filename"],
            "size_bytes": len(raw), "sha256": sha256,
        })
    except (AttachmentRejected, OSError) as exc:
        raise HTTPException(409, "Payroll source file could not be verified after upload") from exc
    row = PayrollEvidenceFile(
        **metadata,
        request_digest=request_digest,
        digest=_digest(metadata),
        snapshot=metadata,
        actor=actor,
    )
    session.add(row)
    await session.flush()
    return result(row)


async def file_for(session, org_id: int, file_id: int, *, kind: str | None = None,
                   employment_binding_id: int | None = None, month: str | None = None):
    row = await session.scalar(select(PayrollEvidenceFile).where(
        PayrollEvidenceFile.id == file_id,
        PayrollEvidenceFile.organization_id == org_id,
    ))
    if (row is None or (kind is not None and row.kind != kind)
            or (employment_binding_id is not None
                and row.employment_binding_id != employment_binding_id)
            or (month is not None and row.month != month)):
        raise AccountingError("Payroll source file does not belong to this calculation scope")
    await run_in_threadpool(verify_bytes, row)
    return row
