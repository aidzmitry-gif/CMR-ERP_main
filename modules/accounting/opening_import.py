"""Atomic opening-balance import with durable source and control-total evidence."""
from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select

from modules.accounting import service
from modules.accounting.models import OpeningImportReceipt
from modules.accounting.schemas import ImportInput


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def package_command_digest(data: ImportInput) -> str:
    command = data.model_dump(mode="json")
    # The request key is transport idempotency, not package content.  A second
    # key for the same source package must be rejected as a duplicate package.
    command.pop("request_key", None)
    return _digest(command)


def _control_totals(data: ImportInput) -> dict[str, str | int]:
    debit = sum(
        (line.amount for entry in data.entries for line in entry.lines if line.side == "debit"),
        Decimal("0"),
    )
    credit = sum(
        (line.amount for entry in data.entries for line in entry.lines if line.side == "credit"),
        Decimal("0"),
    )
    return {
        "entry_count": len(data.entries),
        "line_count": sum(len(entry.lines) for entry in data.entries),
        "debit_byn": format(debit, "f"),
        "credit_byn": format(credit, "f"),
    }


def _entry_snapshot(data: ImportInput, entry_ids: list[int] | None = None) -> list[dict]:
    return [
        {
            "source": entry.source,
            "source_version": entry.source_version,
            "operation": entry.operation,
            "posting_date": entry.posting_date.isoformat(),
            "digest": service.digest(entry),
            **({"entry_id": entry_ids[index]} if entry_ids is not None else {}),
        }
        for index, entry in enumerate(data.entries)
    ]


def _receipt_payload(data: ImportInput, entry_ids: list[int]) -> dict:
    return {
        "organization_id": None,
        "request_key": str(data.request_key),
        "batch": data.batch,
        "protocol_version": data.protocol_version,
        "source_system": data.source_system,
        "source_digest": data.source_digest,
        "cutover_date": data.cutover_date.isoformat(),
        "control_totals": _control_totals(data),
        "evidence": data.evidence,
        "entries": _entry_snapshot(data, entry_ids),
    }


def _result(receipt: OpeningImportReceipt) -> dict:
    return {
        "organization_id": receipt.organization_id,
        "receipt_id": receipt.id,
        "request_key": receipt.request_key,
        "batch": receipt.batch,
        "protocol_version": receipt.protocol_version,
        "source_system": receipt.source_system,
        "source_digest": receipt.source_digest,
        "command_digest": receipt.command_digest,
        "cutover_date": receipt.cutover_date.isoformat(),
        "control_totals": {
            "entry_count": receipt.entry_count,
            "line_count": receipt.line_count,
            "debit_byn": format(receipt.debit_total, "f"),
            "credit_byn": format(receipt.credit_total, "f"),
        },
        "evidence": receipt.evidence,
        "entry_ids": receipt.entry_ids,
        "snapshot": receipt.snapshot,
        "digest": receipt.digest,
        "actor": receipt.actor,
        "created_at": receipt.created_at,
        "confirmed": True,
    }


async def _existing(session, org_id: int, request_key: UUID, command_digest: str,
                    cutover_date: date) -> OpeningImportReceipt | None:
    receipt = await session.scalar(select(OpeningImportReceipt).where(
        OpeningImportReceipt.organization_id == org_id,
        OpeningImportReceipt.request_key == str(request_key),
    ))
    if receipt is not None:
        if receipt.command_digest != command_digest:
            raise service.AccountingError("Opening import request key was reused with different content")
        return receipt
    duplicate = await session.scalar(select(OpeningImportReceipt).where(
        OpeningImportReceipt.organization_id == org_id,
        OpeningImportReceipt.command_digest == command_digest,
    ))
    if duplicate is not None:
        raise service.AccountingError("Opening import package was already accepted with another request key")
    same_cutover = await session.scalar(select(OpeningImportReceipt).where(
        OpeningImportReceipt.organization_id == org_id,
        OpeningImportReceipt.cutover_date == cutover_date,
    ))
    if same_cutover is not None:
        raise service.AccountingError("Opening import already exists for this organization and cutover date")
    return None


async def preview(session, org_id: int, data: ImportInput) -> dict:
    await service.lock_organization(session, org_id)
    command_digest = package_command_digest(data)
    existing = await _existing(session, org_id, data.request_key, command_digest, data.cutover_date)
    if existing is not None:
        return {**_result(existing), "command_digest": command_digest, "already_confirmed": True}
    for entry in data.entries:
        await service.preview_posting(session, org_id, entry)
    return {
        "organization_id": org_id,
        "request_key": str(data.request_key),
        "batch": data.batch,
        "protocol_version": data.protocol_version,
        "source_system": data.source_system,
        "source_digest": data.source_digest,
        "cutover_date": data.cutover_date.isoformat(),
        "command_digest": command_digest,
        "control_totals": _control_totals(data),
        "entries": _entry_snapshot(data),
        "balanced": True,
        "evidence": data.evidence,
        "confirmed": False,
    }


async def confirm(session, org_id: int, data: ImportInput, actor: str, event_bus=None) -> dict:
    await service.lock_organization(session, org_id)
    command_digest = package_command_digest(data)
    existing = await _existing(session, org_id, data.request_key, command_digest, data.cutover_date)
    if existing is not None:
        return _result(existing)
    for entry in data.entries:
        await service.preview_posting(session, org_id, entry)
    entry_ids = [
        (await service.post(session, org_id, entry, actor, event_bus)).id
        for entry in data.entries
    ]
    payload = _receipt_payload(data, entry_ids)
    payload["organization_id"] = org_id
    receipt = OpeningImportReceipt(
        organization_id=org_id,
        request_key=str(data.request_key),
        batch=data.batch,
        protocol_version=data.protocol_version,
        source_system=data.source_system,
        source_digest=data.source_digest,
        cutover_date=data.cutover_date,
        entry_count=len(data.entries),
        line_count=sum(len(entry.lines) for entry in data.entries),
        debit_total=Decimal(data.expected_debit_byn),
        credit_total=Decimal(data.expected_credit_byn),
        command_digest=command_digest,
        evidence=data.evidence,
        entry_ids=entry_ids,
        snapshot=payload,
        digest=_digest(payload),
        actor=actor,
    )
    session.add(receipt)
    await session.flush()
    service.audit(session, org_id, actor, "opening_import_confirmed", {
        "receipt_id": receipt.id,
        "request_key": receipt.request_key,
        "command_digest": command_digest,
        "source_digest": data.source_digest,
        "entry_ids": entry_ids,
    })
    return _result(receipt)


async def list_receipts(session, org_id: int) -> list[dict]:
    await service.lock_organization(session, org_id)
    rows = (await session.scalars(select(OpeningImportReceipt).where(
        OpeningImportReceipt.organization_id == org_id,
    ).order_by(OpeningImportReceipt.id.desc()).limit(100))).all()
    return [_result(row) for row in rows]
