"""Verified payroll import into production cost.

The HR module may calculate or hold payroll, but it is not the statutory
accounting source yet.  This workflow accepts only an explicitly verified
external/imported accrual with line-level evidence, binds each line to an
organization-owned production order, and requires a separate accountant
confirmation before creating a ledger entry.
"""
from __future__ import annotations

import hashlib
import json
from calendar import monthrange
from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator
from sqlalchemy import select

from modules.accounting import service
from modules.accounting.models import Entry, Policy, ProductionLaborReceipt
from modules.accounting.production_cost_policy import validate_accounts
from modules.accounting.schemas import Code, Input, Money, PostingInput, ProductionCostPolicyInput
from modules.accounting.service import AccountingError, lock_organization


class ProductionLaborLine(Input):
    """One verified payroll accrual allocated to one production cost target."""

    source_line_id: str = Field(min_length=1, max_length=128)
    employee: str = Field(min_length=1, max_length=200)
    order_id: int | None = Field(default=None, gt=0, strict=True)
    order_analytics: str | None = Field(default=None, min_length=1, max_length=200)
    department: str = Field(min_length=1, max_length=200)
    cost_account: Code
    role: Literal["direct", "overhead"]
    amount_byn: Money = Field(gt=0)
    evidence: str = Field(min_length=10, max_length=1000)

    @model_validator(mode="after")
    def validate_target(self):
        if self.role == "direct" and (self.order_id is None or not self.order_analytics):
            raise ValueError("Direct labor requires a production order and analytic")
        if self.role == "overhead" and self.order_id is not None and not self.order_analytics:
            raise ValueError("An overhead order identity requires its analytic")
        return self


class ProductionLaborInput(Input):
    request_key: UUID
    source_document: str = Field(min_length=1, max_length=120)
    source_version: int = Field(gt=0, strict=True)
    source_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    verified_by: str = Field(min_length=1, max_length=200)
    source_evidence: str = Field(min_length=10, max_length=2000)
    policy_id: int = Field(gt=0, strict=True)
    posting_date: date
    payroll_account: Code
    lines: list[ProductionLaborLine] = Field(min_length=1, max_length=10000)

    @model_validator(mode="after")
    def validate_identity(self):
        if self.source_version != 1:
            raise ValueError("Payroll corrections require a dedicated correction workflow")
        if "\x00" in self.source_document or "\x00" in self.verified_by:
            raise ValueError("Payroll source identity contains an invalid character")
        ids = [line.source_line_id for line in self.lines]
        if len(ids) != len(set(ids)):
            raise ValueError("Payroll source line identities must be unique")
        return self


class ProductionLaborConfirmInput(ProductionLaborInput):
    digest: str = Field(pattern=r"^[a-f0-9]{64}$")


def _month_bounds(month: str) -> tuple[date, date]:
    try:
        first = date.fromisoformat(month + "-01")
    except ValueError as exc:
        raise AccountingError("Month must be YYYY-MM") from exc
    if first.strftime("%Y-%m") != month:
        raise AccountingError("Month must be YYYY-MM")
    return first, first.replace(day=monthrange(first.year, first.month)[1])


async def _load_policy(session, org_id: int, month: str, data: ProductionLaborInput,
                       *, current: bool):
    first, last = _month_bounds(month)
    if data.posting_date < first or data.posting_date > last:
        raise AccountingError("Payroll posting date must belong to the selected period")
    if current:
        policy = await session.scalar(select(Policy).where(
            Policy.organization_id == org_id, Policy.effective_from <= last,
        ).order_by(Policy.effective_from.desc()))
        if policy is None or policy.id != data.policy_id or policy.effective_from > first:
            raise AccountingError("Select one applicable production policy for the whole reviewed month")
    else:
        policy = await session.scalar(select(Policy).where(
            Policy.organization_id == org_id, Policy.id == data.policy_id,
        ))
        if policy is None or policy.organization_id != org_id:
            raise AccountingError("The saved production policy is not available for this source")
    if policy.production_costing is None:
        raise AccountingError("Production cost configuration is required")
    settings = ProductionCostPolicyInput.model_validate(policy.production_costing)
    await validate_accounts(session, org_id, last, settings)
    accounts = await service.accounts_on(session, org_id, data.posting_date)
    payroll = accounts.get(data.payroll_account)
    if payroll is None:
        raise AccountingError("The payroll payable account is not effective for this organization and date")
    if (payroll.category != "liability" or payroll.cash or payroll.currency_tracking
            or payroll.quantity_tracking):
        raise AccountingError("Payroll payable account must be a noncash BYN liability without quantity tracking")
    return first, last, policy, settings, accounts


def _source_snapshot(org_id: int, month: str, data: ProductionLaborInput,
                     order_snapshots: list[dict]) -> dict:
    return {
        "organization_id": org_id,
        "month": month,
        "source_document": data.source_document,
        "source_version": data.source_version,
        "source_digest": data.source_digest,
        "verified_by": data.verified_by,
        "source_evidence": data.source_evidence,
        "lines": [line.model_dump(mode="json") for line in data.lines],
        "production_orders": order_snapshots,
        "scope": "verified_payroll_import",
        "status": "verified_source_review",
    }


def _posting(org_id: int, month: str, data: ProductionLaborInput, policy: Policy,
             settings: ProductionCostPolicyInput) -> PostingInput:
    posting_lines = []
    for line in data.lines:
        dimensions = {"department": line.department}
        if line.role == "direct":
            if line.cost_account != settings.wip_account:
                raise AccountingError("Direct labor must use the configured WIP account")
            dimensions[settings.order_dimension] = line.order_analytics
        elif line.cost_account not in settings.overhead_accounts:
            raise AccountingError("Overhead labor must use a configured overhead account")
        posting_lines.append({
            "account": line.cost_account,
            "side": "debit",
            "amount": line.amount_byn,
            "dimensions": dimensions,
        })
        posting_lines.append({
            "account": data.payroll_account,
            "side": "credit",
            "amount": line.amount_byn,
            "dimensions": {"employee": line.employee},
        })
    return PostingInput(
        source=f"production:labor:{org_id}:{data.source_document}",
        source_version=1,
        operation="production_labor_import",
        document_date=data.posting_date,
        operation_date=data.posting_date,
        posting_date=data.posting_date,
        policy_id=policy.id,
        rule_version="verified-payroll-import-v1:" + data.source_digest,
        explanation=f"Проверенное начисление труда за {month}; источник {data.source_document}",
        lines=posting_lines,
    )


async def prepare_labor_import(session, org_id: int, month: str, data: ProductionLaborInput,
                               production):
    if production is None:
        raise AccountingError("Production order verification service is unavailable")
    await lock_organization(session, org_id)
    _, _, policy, settings, _ = await _load_policy(session, org_id, month, data, current=True)
    order_ids = sorted({line.order_id for line in data.lines if line.order_id is not None})
    order_snapshots = await production.cost_orders(session, org_id, order_ids) if order_ids else []
    if len(order_snapshots) != len(order_ids):
        raise AccountingError("Production order verification returned an unexpected result")
    source = _source_snapshot(org_id, month, data, order_snapshots)
    posting = _posting(org_id, month, data, policy, settings)
    await service.validate_posting(session, org_id, posting, production_labor_import=True)
    result = {
        "organization_id": org_id,
        "month": month,
        "policy_id": policy.id,
        "source": source,
        "posting_document": posting.model_dump(mode="json"),
        "source_digest": data.source_digest,
        "digest": service.digest(posting),
        "status": "reviewed_verified_payroll",
        "posting_available": True,
        "posted": False,
        "final_cost_certified": False,
    }
    result["basis_digest"] = hashlib.sha256(
        json.dumps(source, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()
    return result


async def confirm_labor_import(session, org_id: int, month: str,
                               data: ProductionLaborConfirmInput, actor, event_bus=None,
                               production=None):
    # Serialize the replay lookup before rebuilding the posting.  A concurrent
    # retry must see the committed receipt and return it; validating a fresh
    # posting first would reject the retry as a later source version.
    await lock_organization(session, org_id)
    incoming = data.model_dump(mode="json")

    async def replay(receipt: ProductionLaborReceipt | None, *, ignore_request_key: bool = False):
        if receipt is None:
            return None
        expected = dict(incoming)
        stored = dict(receipt.command or {})
        if ignore_request_key:
            expected.pop("request_key", None)
            stored.pop("request_key", None)
        if (stored != expected or receipt.digest != data.digest
                or receipt.source_digest != data.source_digest):
            raise AccountingError("Payroll receipt was reused with different content")
        entry = await session.get(Entry, receipt.entry_id)
        if (entry is None or entry.organization_id != org_id
                or entry.digest != receipt.digest
                or entry.source != f"production:labor:{org_id}:{receipt.source_document}"
                or entry.source_version != receipt.source_version):
            raise AccountingError("Payroll receipt has no matching ledger entry")
        return entry

    existing = await session.scalar(select(ProductionLaborReceipt).where(
        ProductionLaborReceipt.organization_id == org_id,
        ProductionLaborReceipt.request_key == str(data.request_key),
    ))
    replayed = await replay(existing)
    if replayed is not None:
        return replayed
    existing_source = await session.scalar(select(ProductionLaborReceipt).where(
        ProductionLaborReceipt.organization_id == org_id,
        ProductionLaborReceipt.source_document == data.source_document,
        ProductionLaborReceipt.source_version == data.source_version,
    ))
    replayed = await replay(existing_source, ignore_request_key=True)
    if replayed is not None:
        return replayed

    prepared = await prepare_labor_import(session, org_id, month, data, production)
    if prepared["digest"] != data.digest:
        raise AccountingError("Payroll posting changed; review it again")
    if prepared["source_digest"] != data.source_digest:
        raise AccountingError("Payroll source changed; review it again")
    entry = await service.post(session, org_id, PostingInput.model_validate(prepared["posting_document"]),
                               actor, event_bus, production_labor_import=True)
    session.add(ProductionLaborReceipt(
        entry_id=entry.id,
        organization_id=org_id,
        month=month,
        request_key=str(data.request_key),
        source_document=data.source_document,
        source_version=data.source_version,
        source_digest=data.source_digest,
        command=data.model_dump(mode="json"),
        source=prepared["source"],
        posting=prepared["posting_document"],
        digest=prepared["digest"],
        actor=actor,
    ))
    await session.flush()
    return entry


async def labor_import_result(session, org_id: int, request_key: UUID):
    return await session.scalar(select(ProductionLaborReceipt).where(
        ProductionLaborReceipt.organization_id == org_id,
        ProductionLaborReceipt.request_key == str(request_key),
    ))
