"""Verified gross-payroll accrual import into the accounting ledger.

The HR module is not yet the statutory payroll source.  This workflow therefore
accepts only an explicitly verified external/imported accrual package, keeps
line-level evidence, and requires a separate accountant confirmation.  It
posts gross accruals (debit cost or WIP, credit payroll payable); deductions,
contributions and statutory reports require their own reviewed workflow.
"""
from __future__ import annotations

import hashlib
import json
from calendar import monthrange
from datetime import date
from uuid import UUID

from pydantic import Field, model_validator
from sqlalchemy import select

from modules.accounting import service
from modules.accounting.models import Entry, PayrollAccrualReceipt, Policy
from modules.accounting.payroll_source_binding import (
    canonical_command,
    canonical_line,
    verify_lines,
)
from modules.accounting.schemas import Code, Input, Money, PostingInput
from modules.accounting.service import AccountingError, lock_organization

_DIMENSIONS = {
    "counterparty", "contract", "settlement_document", "warehouse", "sku", "lot",
    "order", "employee", "asset", "department", "owner", "serial",
}


class PayrollAccrualLine(Input):
    """One externally verified gross accrual and its accounting target."""

    source_line_id: str = Field(min_length=1, max_length=128)
    employment_binding_id: int | None = Field(default=None, gt=0, strict=True)
    employee: str = Field(min_length=1, max_length=200)
    department: str = Field(min_length=1, max_length=200)
    debit_account: Code
    amount_byn: Money = Field(gt=0)
    dimensions: dict[str, str] = Field(default_factory=dict)
    evidence: str = Field(min_length=10, max_length=1000)

    @model_validator(mode="after")
    def validate_dimensions(self):
        for key, value in self.dimensions.items():
            if (key not in _DIMENSIONS or not key.strip() or not isinstance(value, str)
                    or not value.strip() or len(value) > 200 or "\x00" in key or "\x00" in value):
                raise ValueError("Payroll analytic dimensions must be known, nonempty and bounded")
        for key, expected in (("employee", self.employee), ("department", self.department)):
            supplied = self.dimensions.get(key)
            if supplied is not None and supplied != expected:
                raise ValueError(f"Payroll {key} analytic must match the line identity")
        return self


class PayrollAccrualInput(Input):
    request_key: UUID
    source_document: str = Field(min_length=1, max_length=120)
    source_version: int = Field(gt=0, strict=True)
    source_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    verified_by: str = Field(min_length=1, max_length=200)
    source_evidence: str = Field(min_length=10, max_length=2000)
    policy_id: int = Field(gt=0, strict=True)
    posting_date: date
    payroll_account: Code
    lines: list[PayrollAccrualLine] = Field(min_length=1, max_length=10000)

    @model_validator(mode="after")
    def validate_identity(self):
        if self.source_version != 1:
            raise ValueError("Payroll corrections require a dedicated correction workflow")
        if "\x00" in self.source_document or "\x00" in self.verified_by:
            raise ValueError("Payroll source identity contains an invalid character")
        identities = [line.source_line_id for line in self.lines]
        if len(identities) != len(set(identities)):
            raise ValueError("Payroll source line identities must be unique")
        return self


class PayrollAccrualConfirmInput(PayrollAccrualInput):
    digest: str = Field(pattern=r"^[a-f0-9]{64}$")


def _month_bounds(month: str) -> tuple[date, date]:
    try:
        first = date.fromisoformat(month + "-01")
    except ValueError as exc:
        raise AccountingError("Month must be YYYY-MM") from exc
    if first.strftime("%Y-%m") != month:
        raise AccountingError("Month must be YYYY-MM")
    return first, first.replace(day=monthrange(first.year, first.month)[1])


async def _load_policy(session, org_id: int, month: str, data: PayrollAccrualInput,
                       *, current: bool):
    first, last = _month_bounds(month)
    if data.posting_date < first or data.posting_date > last:
        raise AccountingError("Payroll posting date must belong to the selected period")
    if current:
        policy = await session.scalar(select(Policy).where(
            Policy.organization_id == org_id, Policy.effective_from <= last,
        ).order_by(Policy.effective_from.desc()))
        if policy is None or policy.id != data.policy_id or policy.effective_from > first:
            raise AccountingError("Select one applicable accounting policy for the whole reviewed month")
    else:
        policy = await session.scalar(select(Policy).where(
            Policy.organization_id == org_id, Policy.id == data.policy_id,
        ))
        if policy is None or policy.organization_id != org_id:
            raise AccountingError("The saved accounting policy is not available for this source")
    accounts = await service.accounts_on(session, org_id, data.posting_date)
    payroll = accounts.get(data.payroll_account)
    if payroll is None:
        raise AccountingError("The payroll payable account is not effective for this organization and date")
    if (payroll.category != "liability" or payroll.cash or payroll.currency_tracking
            or payroll.quantity_tracking):
        raise AccountingError("Payroll payable account must be a noncash BYN liability without quantity tracking")
    for line in data.lines:
        debit = accounts.get(line.debit_account)
        if debit is None:
            raise AccountingError(f"Payroll debit account {line.debit_account} is not effective for this organization")
        if debit.category not in {"asset", "expense"} or debit.cash or debit.currency_tracking or debit.quantity_tracking:
            raise AccountingError("Payroll debit accounts must be noncash BYN cost or WIP accounts")
    await verify_lines(session, org_id, last, data.lines)
    return first, last, policy, accounts


def _source_snapshot(org_id: int, month: str, data: PayrollAccrualInput) -> dict:
    return {
        "organization_id": org_id,
        "month": month,
        "source_document": data.source_document,
        "source_version": data.source_version,
        "source_digest": data.source_digest,
        "verified_by": data.verified_by,
        "source_evidence": data.source_evidence,
        "lines": [canonical_line(line) for line in data.lines],
        "scope": "verified_payroll_accrual_import",
        "status": "verified_source_review",
        "statutory_payroll_certified": False,
    }


def _posting(org_id: int, month: str, data: PayrollAccrualInput, policy: Policy) -> PostingInput:
    posting_lines = []
    for line in data.lines:
        debit_dimensions = {**line.dimensions, "employee": line.employee, "department": line.department}
        posting_lines.append({
            "account": line.debit_account,
            "side": "debit",
            "amount": line.amount_byn,
            "dimensions": debit_dimensions,
        })
        posting_lines.append({
            "account": data.payroll_account,
            "side": "credit",
            "amount": line.amount_byn,
            "dimensions": {"employee": line.employee, "department": line.department},
        })
    return PostingInput(
        source=f"payroll:accrual:{org_id}:{data.source_document}",
        source_version=1,
        operation="payroll_accrual_import",
        document_date=data.posting_date,
        operation_date=data.posting_date,
        posting_date=data.posting_date,
        policy_id=policy.id,
        rule_version="verified-payroll-accrual-import-v1:" + data.source_digest,
        explanation=f"Проверенное валовое начисление зарплаты за {month}; источник {data.source_document}",
        lines=posting_lines,
    )


async def prepare_payroll_accrual(session, org_id: int, month: str, data: PayrollAccrualInput):
    await lock_organization(session, org_id)
    _, _, policy, _ = await _load_policy(session, org_id, month, data, current=True)
    source = _source_snapshot(org_id, month, data)
    posting = _posting(org_id, month, data, policy)
    await service.validate_posting(session, org_id, posting, payroll_accrual_import=True)
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
        "statutory_payroll_certified": False,
        "deductions_and_contributions_available": False,
        "stable_employment_mapping_complete": all(
            line.employment_binding_id is not None for line in data.lines),
    }
    result["basis_digest"] = hashlib.sha256(
        json.dumps(source, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()
    return result


async def confirm_payroll_accrual(session, org_id: int, month: str,
                                  data: PayrollAccrualConfirmInput, actor, event_bus=None):
    await lock_organization(session, org_id)
    incoming = canonical_command(data)

    async def replay(receipt: PayrollAccrualReceipt | None, *, ignore_request_key: bool = False):
        if receipt is None:
            return None
        expected = dict(incoming)
        stored = dict(receipt.command or {})
        if ignore_request_key:
            expected.pop("request_key", None)
            stored.pop("request_key", None)
        if (stored != expected or receipt.digest != data.digest
                or receipt.source_digest != data.source_digest):
            raise AccountingError("Payroll accrual receipt was reused with different content")
        entry = await session.get(Entry, receipt.entry_id)
        expected_source = f"payroll:accrual:{org_id}:{receipt.source_document}"
        if (entry is None or entry.organization_id != org_id
                or entry.operation != "payroll_accrual_import"
                or entry.digest != receipt.digest
                or entry.source != expected_source
                or entry.source_version != receipt.source_version):
            raise AccountingError("Payroll accrual receipt has no matching ledger entry")
        return entry

    existing = await session.scalar(select(PayrollAccrualReceipt).where(
        PayrollAccrualReceipt.organization_id == org_id,
        PayrollAccrualReceipt.request_key == str(data.request_key),
    ))
    replayed = await replay(existing)
    if replayed is not None:
        return replayed
    existing_source = await session.scalar(select(PayrollAccrualReceipt).where(
        PayrollAccrualReceipt.organization_id == org_id,
        PayrollAccrualReceipt.source_document == data.source_document,
        PayrollAccrualReceipt.source_version == data.source_version,
    ))
    replayed = await replay(existing_source, ignore_request_key=True)
    if replayed is not None:
        return replayed

    prepared = await prepare_payroll_accrual(session, org_id, month, data)
    if prepared["digest"] != data.digest:
        raise AccountingError("Payroll accrual posting changed; review it again")
    if prepared["source_digest"] != data.source_digest:
        raise AccountingError("Payroll accrual source changed; review it again")
    entry = await service.post(
        session, org_id, PostingInput.model_validate(prepared["posting_document"]),
        actor, event_bus, payroll_accrual_import=True,
    )
    session.add(PayrollAccrualReceipt(
        entry_id=entry.id,
        organization_id=org_id,
        month=month,
        request_key=str(data.request_key),
        source_document=data.source_document,
        source_version=data.source_version,
        source_digest=data.source_digest,
        command=canonical_command(data),
        source=prepared["source"],
        posting=prepared["posting_document"],
        digest=prepared["digest"],
        actor=actor,
    ))
    await session.flush()
    return entry


async def payroll_accrual_result(session, org_id: int, request_key: UUID):
    return await session.scalar(select(PayrollAccrualReceipt).where(
        PayrollAccrualReceipt.organization_id == org_id,
        PayrollAccrualReceipt.request_key == str(request_key),
    ))
