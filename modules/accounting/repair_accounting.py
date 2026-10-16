"""Reviewed accounting package for paid and warranty repairs.

The service module owns the repair request.  Accounting receives an explicit,
versioned evidence package and never infers ownership, coverage, serial
number, or cost from the current service status.  Customer supplied material
is recorded in the source snapshot with zero accounting value; it cannot be
turned into an owned inventory credit.
"""
from __future__ import annotations

import hashlib
import json
from calendar import monthrange
from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator
from sqlalchemy import select

from modules.accounting import service
from modules.accounting.models import Entry, Policy, RepairAccountingReceipt
from modules.accounting.schemas import Code, Input, Money, PostingInput
from modules.accounting.service import AccountingError, lock_organization


class RepairCostLine(Input):
    source_line_id: str = Field(min_length=1, max_length=128)
    kind: Literal["material", "labor", "external"]
    material_owner: Literal["own", "customer"] = "own"
    description: str = Field(min_length=1, max_length=300)
    amount_byn: Money
    debit_account: Code | None = None
    credit_account: Code | None = None
    dimensions: dict[str, str] = Field(default_factory=dict)
    evidence: str = Field(min_length=10, max_length=1000)

    @model_validator(mode="after")
    def validate_ownership(self):
        if self.material_owner == "customer":
            if self.kind != "material":
                raise ValueError("Customer-owned lines must be materials")
            if self.amount_byn != Decimal("0") or self.debit_account or self.credit_account:
                raise ValueError("Customer-owned material must not create an owned accounting value")
        else:
            if self.amount_byn <= 0 or not self.debit_account or not self.credit_account:
                raise ValueError("Owned repair cost needs positive amount and both accounts")
        if any(not key.strip() or not value.strip() or len(key) > 100 or len(value) > 200
               or "\x00" in key or "\x00" in value for key, value in self.dimensions.items()):
            raise ValueError("Repair analytical identifiers must be nonempty and bounded")
        return self


class RepairAccountingInput(Input):
    request_key: UUID
    service_request_id: int = Field(gt=0, strict=True)
    source_document: str = Field(min_length=1, max_length=160)
    source_version: int = Field(gt=0, strict=True)
    source_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    serial_number: str = Field(min_length=1, max_length=160)
    owner_type: Literal["customer", "organization"]
    owner_reference: str = Field(min_length=1, max_length=200)
    coverage: Literal["paid", "warranty"]
    counterparty_reference: str | None = Field(default=None, min_length=1, max_length=200)
    policy_id: int = Field(gt=0, strict=True)
    posting_date: date
    service_amount_byn: Money
    settlement_account: Code | None = None
    revenue_account: Code | None = None
    source_evidence: str = Field(min_length=10, max_length=2000)
    lines: list[RepairCostLine] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_terms(self):
        if self.source_version != 1:
            raise ValueError("Repair corrections require a dedicated correction workflow")
        if "\x00" in self.source_document or "\x00" in self.owner_reference:
            raise ValueError("Repair source identity contains an invalid character")
        ids = [line.source_line_id for line in self.lines]
        if len(ids) != len(set(ids)):
            raise ValueError("Repair source line identities must be unique")
        if self.coverage == "paid":
            if self.service_amount_byn <= 0 or not self.settlement_account or not self.revenue_account:
                raise ValueError("Paid repair needs a positive service amount and settlement/revenue accounts")
            if self.counterparty_reference is None:
                raise ValueError("Paid repair needs a counterparty reference")
            if self.settlement_account == self.revenue_account:
                raise ValueError("Settlement and revenue accounts must differ")
        elif self.service_amount_byn != Decimal("0") or self.settlement_account or self.revenue_account:
            raise ValueError("Warranty repair must not carry paid-service revenue terms")
        if self.coverage == "warranty" and not any(
            line.material_owner == "own" and line.amount_byn > 0 for line in self.lines
        ):
            raise ValueError("Warranty repair needs at least one owned cost line")
        return self


class RepairAccountingConfirmInput(RepairAccountingInput):
    digest: str = Field(pattern=r"^[a-f0-9]{64}$")


def _month_bounds(month: str) -> tuple[date, date]:
    try:
        first = date.fromisoformat(month + "-01")
    except ValueError as exc:
        raise AccountingError("Month must be YYYY-MM") from exc
    if first.strftime("%Y-%m") != month:
        raise AccountingError("Month must be YYYY-MM")
    return first, first.replace(day=monthrange(first.year, first.month)[1])


def _dimensions(data: RepairAccountingInput, line: RepairCostLine) -> dict[str, str]:
    dimensions = dict(line.dimensions)
    defaults = {
        "owner": f"{data.owner_type}:{data.owner_reference}",
        "serial": data.serial_number,
        "order": str(data.service_request_id),
    }
    if data.counterparty_reference:
        defaults["counterparty"] = data.counterparty_reference
    for key, value in defaults.items():
        if key in dimensions and dimensions[key] != value:
            raise AccountingError(f"Repair dimension {key} does not match the reviewed source")
        dimensions[key] = value
    return dimensions


def _source_snapshot(org_id: int, month: str, data: RepairAccountingInput) -> dict:
    return {
        "organization_id": org_id,
        "month": month,
        "scope": "repair_accounting",
        "service_request_id": data.service_request_id,
        "source_document": data.source_document,
        "source_version": data.source_version,
        "source_digest": data.source_digest,
        "serial_number": data.serial_number,
        "owner_type": data.owner_type,
        "owner_reference": data.owner_reference,
        "coverage": data.coverage,
        "counterparty_reference": data.counterparty_reference,
        "source_evidence": data.source_evidence,
        "lines": [line.model_dump(mode="json") for line in data.lines],
        "customer_material_lines": [line.source_line_id for line in data.lines
                                     if line.material_owner == "customer"],
    }


def _posting(org_id: int, month: str, data: RepairAccountingInput, policy: Policy) -> PostingInput:
    posting_lines: list[dict] = []
    cost_total = Decimal("0")
    for line in data.lines:
        if line.material_owner == "customer":
            continue
        assert line.debit_account and line.credit_account
        dimensions = _dimensions(data, line)
        posting_lines.append({
            "account": line.debit_account,
            "side": "debit",
            "amount": line.amount_byn,
            "dimensions": dimensions,
        })
        posting_lines.append({
            "account": line.credit_account,
            "side": "credit",
            "amount": line.amount_byn,
            "dimensions": dimensions,
        })
        cost_total += line.amount_byn
    if data.coverage == "paid":
        assert data.settlement_account and data.revenue_account and data.counterparty_reference
        dimensions = _dimensions(data, RepairCostLine(
            source_line_id="service", kind="external", description="Услуга ремонта",
            amount_byn=data.service_amount_byn, debit_account=data.settlement_account,
            credit_account=data.revenue_account, evidence=data.source_evidence,
        ))
        posting_lines.extend([
            {"account": data.settlement_account, "side": "debit", "amount": data.service_amount_byn,
             "dimensions": dimensions},
            {"account": data.revenue_account, "side": "credit", "amount": data.service_amount_byn,
             "dimensions": dimensions},
        ])
    return PostingInput(
        source=f"service:repair:{org_id}:{data.service_request_id}",
        source_version=data.source_version,
        operation="repair_service",
        document_date=data.posting_date,
        operation_date=data.posting_date,
        posting_date=data.posting_date,
        policy_id=policy.id,
        rule_version="repair-service-v1:" + data.source_digest,
        explanation=(f"{'Платный' if data.coverage == 'paid' else 'Гарантийный'} ремонт "
                     f"заявки {data.service_request_id}, изделие {data.serial_number}"),
        lines=posting_lines,
    )


async def _load_policy(session, org_id: int, data: RepairAccountingInput, *, current: bool):
    if current:
        statement = select(Policy).where(
            Policy.organization_id == org_id,
            Policy.effective_from <= data.posting_date,
        ).order_by(Policy.effective_from.desc()).limit(1)
    else:
        statement = select(Policy).where(
            Policy.organization_id == org_id,
            Policy.id == data.policy_id,
        )
    policy = await session.scalar(statement)
    if policy is None or policy.organization_id != org_id or policy.id != data.policy_id:
        raise AccountingError("An effective approved organization policy is required")
    return policy


async def prepare_repair(session, org_id: int, month: str, data: RepairAccountingInput):
    first, last = _month_bounds(month)
    if data.posting_date < first or data.posting_date > last:
        raise AccountingError("Repair posting date must belong to the selected period")
    await lock_organization(session, org_id)
    policy = await _load_policy(session, org_id, data, current=True)
    source = _source_snapshot(org_id, month, data)
    posting = _posting(org_id, month, data, policy)
    await service.validate_posting(session, org_id, posting, repair_accounting=True)
    cost_total = sum((line.amount_byn for line in data.lines if line.material_owner == "own"), Decimal("0"))
    result = {
        "organization_id": org_id,
        "month": month,
        "service_request_id": data.service_request_id,
        "serial_number": data.serial_number,
        "owner_type": data.owner_type,
        "owner_reference": data.owner_reference,
        "coverage": data.coverage,
        "source": source,
        "posting_document": posting.model_dump(mode="json"),
        "source_digest": data.source_digest,
        "digest": service.digest(posting),
        "status": "reviewed_repair",
        "posting_available": True,
        "posted": False,
        "final_cost_certified": False,
        "financial_result": {
            "service_amount_byn": format(data.service_amount_byn, ".2f"),
            "cost_amount_byn": format(cost_total, ".2f"),
            "gross_result_byn": format(data.service_amount_byn - cost_total, ".2f"),
            "customer_material_lines": source["customer_material_lines"],
        },
    }
    result["basis_digest"] = hashlib.sha256(
        json.dumps(source, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()
    return result


async def confirm_repair(session, org_id: int, month: str, data: RepairAccountingConfirmInput,
                         actor, event_bus=None):
    # Serialize replay/source-version checks before rebuilding the posting. A
    # concurrent retry must return the committed receipt instead of reaching
    # validate_posting and being mistaken for an illegal later source version.
    await lock_organization(session, org_id)
    existing = await session.scalar(select(RepairAccountingReceipt).where(
        RepairAccountingReceipt.organization_id == org_id,
        RepairAccountingReceipt.request_key == str(data.request_key),
    ))
    existing_source = await session.scalar(select(RepairAccountingReceipt).where(
        RepairAccountingReceipt.organization_id == org_id,
        RepairAccountingReceipt.service_request_id == data.service_request_id,
        RepairAccountingReceipt.source_version == data.source_version,
    ))
    for saved in (existing, existing_source):
        if saved is not None:
            if saved.digest != data.digest or saved.source_digest != data.source_digest:
                raise AccountingError("Repair source version or request key was reused with different content")
            entry = await session.get(Entry, saved.entry_id)
            if entry is None:
                raise AccountingError("Repair receipt has no matching ledger entry")
            return entry
    prepared = await prepare_repair(session, org_id, month, data)
    if prepared["digest"] != data.digest or prepared["source_digest"] != data.source_digest:
        raise AccountingError("Repair source or posting changed; review it again")
    entry = await service.post(session, org_id, PostingInput.model_validate(prepared["posting_document"]),
                               actor, event_bus, repair_accounting=True)
    session.add(RepairAccountingReceipt(
        entry_id=entry.id,
        organization_id=org_id,
        service_request_id=data.service_request_id,
        month=month,
        request_key=str(data.request_key),
        source_version=data.source_version,
        source_digest=data.source_digest,
        serial_number=data.serial_number,
        owner_type=data.owner_type,
        owner_reference=data.owner_reference,
        coverage=data.coverage,
        command=data.model_dump(mode="json"),
        source=prepared["source"],
        posting=prepared["posting_document"],
        financial_result=prepared["financial_result"],
        digest=prepared["digest"],
        actor=actor,
    ))
    await session.flush()
    return entry


def serialize_receipt(row: RepairAccountingReceipt) -> dict:
    return {
        "entry_id": row.entry_id,
        "organization_id": row.organization_id,
        "service_request_id": row.service_request_id,
        "month": row.month,
        "request_key": row.request_key,
        "source_version": row.source_version,
        "source_digest": row.source_digest,
        "serial_number": row.serial_number,
        "owner_type": row.owner_type,
        "owner_reference": row.owner_reference,
        "coverage": row.coverage,
        "source": row.source,
        "posting": row.posting,
        "financial_result": row.financial_result,
        "digest": row.digest,
        "actor": row.actor,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


async def repair_result(session, org_id: int, request_key: UUID):
    return await session.scalar(select(RepairAccountingReceipt).where(
        RepairAccountingReceipt.organization_id == org_id,
        RepairAccountingReceipt.request_key == str(request_key),
    ))


async def repair_rows(session, org_id: int, month: str | None = None):
    query = select(RepairAccountingReceipt).where(
        RepairAccountingReceipt.organization_id == org_id,
    ).order_by(RepairAccountingReceipt.created_at.desc(), RepairAccountingReceipt.entry_id.desc())
    if month:
        query = query.where(RepairAccountingReceipt.month == month)
    return [serialize_receipt(row) for row in (await session.scalars(query)).all()]
