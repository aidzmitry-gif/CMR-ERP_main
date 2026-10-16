"""Reviewed, atomic revisions of production-output cost.

The database derives the source/disposition matrix independently. Raw JSON is
kept for storage and hashing so BYN numbers never round-trip through floats.
"""
from __future__ import annotations

import hashlib
import json
from calendar import monthrange
from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import Field
from sqlalchemy import select, text

from modules.accounting import service
from modules.accounting.closing_commands import actual_posting
from modules.accounting.models import (
    Entry,
    Period,
    Policy,
    ProductionOutputCostRevision,
    ProductionOutputTransferReceipt,
)
from modules.accounting.schemas import Input, LineInput, PostingInput
from modules.accounting.service import AccountingError


class ProductionOutputCostPreviewInput(Input):
    original_entry_id: int = Field(gt=0, strict=True)
    posting_date: date
    request_evidence: str = Field(min_length=1, max_length=1000)


class ProductionOutputCostConfirmInput(ProductionOutputCostPreviewInput):
    request_key: UUID
    basis_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


async def _prepare(session, organization_id, month, data, *, procurement=None):
    await service.lock_organization(session, organization_id)
    first = date.fromisoformat(month + "-01")
    last = first.replace(day=monthrange(first.year, first.month)[1])
    if not first <= data.posting_date <= last:
        raise AccountingError("Output cost correction posting date must belong to the selected period")
    receipt = await session.get(ProductionOutputTransferReceipt, data.original_entry_id)
    if receipt is None or receipt.organization_id != organization_id:
        raise AccountingError("Original production output receipt was not found")
    if receipt.month != month:
        raise AccountingError("Only the original output open period may be corrected")
    original = await session.get(Entry, receipt.entry_id)
    expected = PostingInput.model_validate(receipt.posting)
    if (original is None or original.organization_id != organization_id
            or original.posting_date > data.posting_date or original.digest != receipt.digest
            or service.digest(expected) != receipt.digest
            or (await actual_posting(session, original)).model_dump() != expected.model_dump()):
        raise AccountingError("Original output posting package does not match its receipt")
    if await session.scalar(select(Period.id).where(
        Period.organization_id == organization_id, Period.month >= month, Period.closed.is_(True)
    ).limit(1)) is not None:
        raise AccountingError("Closed-period output corrections require an applicable correction policy; this workflow supports open original periods")
    policy = await session.scalar(select(Policy).where(
        Policy.organization_id == organization_id, Policy.effective_from <= data.posting_date
    ).order_by(Policy.effective_from.desc()).limit(1))
    if policy is None or policy.id != original.policy_id or policy.production_costing is None:
        raise AccountingError("The original applicable production policy is required")
    previous = await session.scalar(select(ProductionOutputCostRevision).where(
        ProductionOutputCostRevision.original_entry_id == receipt.entry_id,
        ProductionOutputCostRevision.organization_id == organization_id,
    ).order_by(ProductionOutputCostRevision.sequence.desc()).limit(1))
    sequence = previous.sequence + 1 if previous else 1
    if previous and previous.command["posting_date"] > data.posting_date.isoformat():
        raise AccountingError("Correction cannot precede the previous revision")
    from modules.accounting.zero_value_disposals import available_authenticated_zero_value_disposals

    # SQL fingerprints bind immutable evidence; the shared Python cost engine
    # independently proves that each source allocation followed its policy.
    if await session.scalar(text(
        "SELECT to_regprocedure('accounting.zero_value_allocation_runtime_version()') IS NOT NULL"
    )) is True:
        await available_authenticated_zero_value_disposals(session, organization_id, procurement=procurement)
    raw = await session.scalar(text(
        "SELECT accounting.output_cost_revision_evidence(:org,:entry,:cutoff,NULL)::text"
    ), {"org": organization_id, "entry": receipt.entry_id, "cutoff": data.posting_date})
    evidence = json.loads(raw, parse_float=str)
    command = ProductionOutputCostPreviewInput.model_validate(data.model_dump(include={
        "original_entry_id", "posting_date", "request_evidence"})).model_dump(mode="json")
    basis = hashlib.sha256(json.dumps({"organization_id": organization_id, "month": month,
        "sequence": sequence, "command": command, "ledger_json": raw},
        sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    posting = None
    if evidence["matrix"]:
        posting = PostingInput(source=f"production:output-cost-revision:{organization_id}:{receipt.entry_id}:{sequence}",
            source_version=1, operation="production_output_cost_correction", document_date=data.posting_date,
            operation_date=data.posting_date, posting_date=data.posting_date, policy_id=policy.id,
            rule_version="production-output-cost-revision-v1", explanation=data.request_evidence,
            correction_of=receipt.entry_id, lines=[LineInput(**{**r, "amount": f"{Decimal(str(r['amount'])):.2f}"}) for r in evidence["matrix"]])
        await service.validate_posting(session, organization_id, posting, production_output_correction=True)
    allocations = evidence["allocation"]
    destinations = []
    disposals = []
    for row in allocations:
        destination = None
        if row["key"] != "remaining" and not row["key"].startswith("remaining:"):
            parts = row["key"].split(":")
            kind = parts[0]
            destination = {"kind": kind, "quantity": f"{Decimal(str(row['quantity'])):.6f}",
                "applied_cost_byn": f"{Decimal(str(row['book'])):.2f}", "destination_account": row["account"],
                "destination_dimensions": row["dimensions"]}
            if kind == "disposed" and len(parts) == 3:
                _, first, second = parts
                destination |= {"entry_id": int(first), "line_id": int(second), "receipt_entry_id": int(first)}
            elif kind == "zero" and len(parts) == 3:
                _, first, second = parts
                destination |= {"receipt_id": int(first), "registration_token": int(second)}
            elif kind == "allocation" and len(parts) == 4:
                destination |= {"entry_id": int(parts[1]), "source_entry_id": int(parts[2]),
                                "source_line_id": int(parts[3])}
            elif kind == "zeroallocation" and len(parts) == 5:
                destination |= {"receipt_id": int(parts[1]), "registration_token": int(parts[2]),
                                "source_entry_id": int(parts[3]), "source_line_id": int(parts[4])}
            else:
                raise AccountingError("Output revision has an unknown disposal identity")
            disposals.append(destination)
        delta = Decimal(str(row["delta"]))
        destinations.append({"key": row["key"], "kind": "disposed" if destination else "remaining",
            "account": row["account"], "dimensions": row["dimensions"],
            "destination": destination, "cents": int(Decimal(str(row["desired"]))*100),
            "delta_cents": int(delta*100), "amount_byn": f"{abs(delta):.2f}", "side": "debit" if delta>=0 else "credit"})
    total = sum((Decimal(str(r["desired"])) for r in allocations), Decimal(0))
    preview = {"status": "preview", "confirmation_available": True, "final_cost_certified": False,
        "organization_id": organization_id, "original_entry_id": receipt.entry_id, "month": month,
        "posting_date": data.posting_date.isoformat(), "request_evidence": data.request_evidence,
        "sequence": sequence, "basis_digest": basis, "ledger_evidence": evidence,
        "source": {"candidate_transfer_byn": f"{total:.2f}", "source_lines": evidence["source_lines"]},
        "trace": {"disposals": disposals}, "destinations": destinations,
        "delta_cents": sum(r["delta_cents"] for r in destinations), "desired_total_byn": f"{total:.2f}",
        "posting_document": posting.model_dump(mode="json") if posting else None}
    return preview, raw, posting, previous


async def preview_output_cost_correction(session, organization_id: int, month: str,
                                         data: ProductionOutputCostPreviewInput, *, procurement=None) -> dict:
    return (await _prepare(session, organization_id, month, data, procurement=procurement))[0]


async def confirm_output_cost_correction(session, organization_id: int, month: str,
                                         data: ProductionOutputCostConfirmInput, actor, event_bus=None, *, procurement=None):
    org = await service.lock_organization(session, organization_id)
    command = data.model_dump(mode="json")
    existing = await session.scalar(select(ProductionOutputCostRevision).where(
        ProductionOutputCostRevision.organization_id == organization_id,
        ProductionOutputCostRevision.request_key == str(data.request_key)))
    if existing:
        if existing.month != month or existing.command != command or existing.actor != actor:
            raise AccountingError("Output cost revision request key was reused with different content")
        if existing.entry_id:
            entry = await session.get(Entry, existing.entry_id)
            saved = PostingInput.model_validate(existing.posting)
            if entry is None or (await actual_posting(session, entry)).model_dump() != saved.model_dump():
                raise AccountingError("Saved output cost revision package changed")
        return existing
    preview, raw, posting, previous = await _prepare(session, organization_id, month, data, procurement=procurement)
    if preview["basis_digest"] != data.basis_digest:
        raise AccountingError("Output cost basis changed; preview again")
    entry = await service.post(session, organization_id, posting, actor, event_bus,
                               production_output_correction=True) if posting else None
    revision_id = await session.scalar(text("""
        INSERT INTO accounting.production_output_cost_revision
        (organization_id, original_entry_id, sequence, previous_id, entry_id, month,
         request_key, command, preview, posting, actor)
        VALUES (:org,:original,:sequence,:previous,:entry,:month,:key,CAST(:command AS json),
          jsonb_build_object('ledger_evidence',CAST(:evidence AS jsonb)),CAST(:posting AS json),:actor)
        RETURNING id
    """), {"org": organization_id, "original": data.original_entry_id, "sequence": preview["sequence"],
        "previous": previous.id if previous else None, "entry": entry.id if entry else None, "month": month,
        "key": str(data.request_key), "command": json.dumps(command), "evidence": raw,
        "posting": json.dumps(posting.model_dump(mode="json")) if posting else None, "actor": actor})
    if not entry:
        period = await service.period_for(session, organization_id, month)
        affected = (await session.scalars(select(Period).where(
            Period.organization_id == organization_id, Period.month >= period.month))).all()
        for item in affected:
            item.generation += 1
            item.evidence = {}
        org.generation += 1
    service.audit(session, organization_id, actor, "production_output_cost_revised",
                  {"revision_id": revision_id, "entry_id": entry.id if entry else None, "basis_digest": data.basis_digest})
    await session.flush()
    return await session.get(ProductionOutputCostRevision, revision_id)
