"""Reviewed import of payroll deductions and employer contributions.

The package contains amounts calculated by an explicitly identified external
payroll source.  This workflow deliberately does not guess Belarusian rates,
derive an amount from a salary, or certify a tax/social report.  It only turns
the reviewed source package into balanced, source-bound accounting entries.
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
from modules.accounting.models import Entry, PayrollStatutoryReceipt, Policy
from modules.accounting.schemas import Code, Input, Money, PostingInput
from modules.accounting.service import AccountingError, lock_organization

_DIMENSIONS = {
    "counterparty", "contract", "settlement_document", "warehouse", "sku", "lot",
    "order", "employee", "asset", "department", "owner", "serial",
}


class PayrollStatutoryLine(Input):
    """One reviewed deduction or employer contribution."""

    source_line_id: str = Field(min_length=1, max_length=128)
    employee: str = Field(min_length=1, max_length=200)
    department: str = Field(min_length=1, max_length=200)
    kind: Literal["employee_deduction", "employer_contribution"]
    liability_account: Code
    cost_account: Code | None = None
    amount_byn: Money = Field(gt=0)
    dimensions: dict[str, str] = Field(default_factory=dict)
    evidence: str = Field(min_length=10, max_length=1000)

    @model_validator(mode="after")
    def validate_line(self):
        if self.kind == "employer_contribution" and self.cost_account is None:
            raise ValueError("Employer contribution requires a cost account")
        if self.kind == "employee_deduction" and self.cost_account is not None:
            raise ValueError("Employee deduction must not carry a cost account")
        for key, value in self.dimensions.items():
            if (key not in _DIMENSIONS or not key.strip() or not isinstance(value, str)
                    or not value.strip() or len(value) > 200 or "\x00" in key or "\x00" in value):
                raise ValueError("Payroll analytic dimensions must be known, nonempty and bounded")
        for key, expected in (("employee", self.employee), ("department", self.department)):
            supplied = self.dimensions.get(key)
            if supplied is not None and supplied != expected:
                raise ValueError(f"Payroll {key} analytic must match the line identity")
        return self


class PayrollStatutoryInput(Input):
    request_key: UUID
    source_document: str = Field(min_length=1, max_length=120)
    source_version: int = Field(gt=0, strict=True)
    source_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    verified_by: str = Field(min_length=1, max_length=200)
    source_evidence: str = Field(min_length=10, max_length=2000)
    policy_id: int = Field(gt=0, strict=True)
    posting_date: date
    payroll_account: Code
    lines: list[PayrollStatutoryLine] = Field(min_length=1, max_length=10000)

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


class PayrollStatutoryConfirmInput(PayrollStatutoryInput):
    digest: str = Field(pattern=r"^[a-f0-9]{64}$")


def _month_bounds(month: str) -> tuple[date, date]:
    try:
        first = date.fromisoformat(month + "-01")
    except ValueError as exc:
        raise AccountingError("Month must be YYYY-MM") from exc
    if first.strftime("%Y-%m") != month:
        raise AccountingError("Month must be YYYY-MM")
    return first, first.replace(day=monthrange(first.year, first.month)[1])


def _is_noncash_byn(row, *, category: set[str], label: str):
    if row is None:
        raise AccountingError(f"{label} is not effective for this organization and date")
    if (row.category not in category or row.cash or row.currency_tracking
            or row.quantity_tracking):
        raise AccountingError(f"{label} must be a noncash BYN account without quantity tracking")


async def _load_policy(session, org_id: int, month: str, data: PayrollStatutoryInput,
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
    has_deductions = any(line.kind == "employee_deduction" for line in data.lines)
    payroll = accounts.get(data.payroll_account)
    if has_deductions:
        _is_noncash_byn(payroll, category={"liability"}, label="Payroll payable account")
    for line in data.lines:
        liability = accounts.get(line.liability_account)
        _is_noncash_byn(liability, category={"liability"}, label="Payroll liability account")
        if line.kind == "employee_deduction":
            if line.liability_account == data.payroll_account:
                raise AccountingError("Employee deduction liability must differ from payroll payable")
        else:
            cost = accounts.get(line.cost_account)
            _is_noncash_byn(cost, category={"asset", "expense"}, label="Contribution cost account")
    return first, last, policy, accounts


def _source_snapshot(org_id: int, month: str, data: PayrollStatutoryInput) -> dict:
    return {
        "organization_id": org_id,
        "month": month,
        "source_document": data.source_document,
        "source_version": data.source_version,
        "source_digest": data.source_digest,
        "verified_by": data.verified_by,
        "source_evidence": data.source_evidence,
        "lines": [line.model_dump(mode="json") for line in data.lines],
        "scope": "verified_payroll_statutory_import",
        "status": "verified_source_review",
        "calculation_mode": "external_verified_import",
        "statutory_payroll_certified": False,
    }


def _posting(org_id: int, month: str, data: PayrollStatutoryInput, policy: Policy) -> PostingInput:
    posting_lines = []
    for line in data.lines:
        dimensions = {**line.dimensions, "employee": line.employee, "department": line.department}
        debit_account = data.payroll_account if line.kind == "employee_deduction" else line.cost_account
        posting_lines.append({
            "account": debit_account,
            "side": "debit",
            "amount": line.amount_byn,
            "dimensions": dimensions,
        })
        posting_lines.append({
            "account": line.liability_account,
            "side": "credit",
            "amount": line.amount_byn,
            "dimensions": dimensions,
        })
    return PostingInput(
        source=f"payroll:statutory:{org_id}:{data.source_document}",
        source_version=1,
        operation="payroll_statutory_import",
        document_date=data.posting_date,
        operation_date=data.posting_date,
        posting_date=data.posting_date,
        policy_id=policy.id,
        rule_version="verified-payroll-statutory-v1:" + data.source_digest,
        explanation=f"Проверенный импорт удержаний и взносов за {month}; источник {data.source_document}",
        lines=posting_lines,
    )


def _totals(data: PayrollStatutoryInput) -> tuple[Decimal, Decimal]:
    deductions = sum((line.amount_byn for line in data.lines if line.kind == "employee_deduction"), Decimal("0"))
    contributions = sum((line.amount_byn for line in data.lines if line.kind == "employer_contribution"), Decimal("0"))
    return deductions, contributions


async def prepare_payroll_statutory(session, org_id: int, month: str,
                                    data: PayrollStatutoryInput):
    await lock_organization(session, org_id)
    _, _, policy, _ = await _load_policy(session, org_id, month, data, current=True)
    source = _source_snapshot(org_id, month, data)
    posting = _posting(org_id, month, data, policy)
    await service.validate_posting(session, org_id, posting, payroll_statutory_import=True)
    deductions, contributions = _totals(data)
    result = {
        "organization_id": org_id,
        "month": month,
        "policy_id": policy.id,
        "source": source,
        "posting_document": posting.model_dump(mode="json"),
        "source_digest": data.source_digest,
        "digest": service.digest(posting),
        "status": "reviewed_verified_payroll_statutory",
        "posting_available": True,
        "posted": False,
        "statutory_payroll_certified": False,
        "deductions_and_contributions_available": True,
        "employee_deductions_byn": format(deductions, "f"),
        "employer_contributions_byn": format(contributions, "f"),
    }
    result["basis_digest"] = hashlib.sha256(
        json.dumps(source, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()
    return result


async def confirm_payroll_statutory(session, org_id: int, month: str,
                                    data: PayrollStatutoryConfirmInput, actor, event_bus=None):
    await lock_organization(session, org_id)
    incoming = data.model_dump(mode="json")

    async def replay(receipt: PayrollStatutoryReceipt | None, *, ignore_request_key: bool = False):
        if receipt is None:
            return None
        expected = dict(incoming)
        stored = dict(receipt.command or {})
        if ignore_request_key:
            expected.pop("request_key", None)
            stored.pop("request_key", None)
        if (stored != expected or receipt.digest != data.digest
                or receipt.source_digest != data.source_digest):
            raise AccountingError("Payroll statutory receipt was reused with different content")
        entry = await session.get(Entry, receipt.entry_id)
        expected_source = f"payroll:statutory:{org_id}:{receipt.source_document}"
        if (entry is None or entry.organization_id != org_id
                or entry.operation != "payroll_statutory_import"
                or entry.digest != receipt.digest
                or entry.source != expected_source
                or entry.source_version != receipt.source_version):
            raise AccountingError("Payroll statutory receipt has no matching ledger entry")
        return entry

    existing = await session.scalar(select(PayrollStatutoryReceipt).where(
        PayrollStatutoryReceipt.organization_id == org_id,
        PayrollStatutoryReceipt.request_key == str(data.request_key),
    ))
    replayed = await replay(existing)
    if replayed is not None:
        return replayed
    existing_source = await session.scalar(select(PayrollStatutoryReceipt).where(
        PayrollStatutoryReceipt.organization_id == org_id,
        PayrollStatutoryReceipt.source_document == data.source_document,
        PayrollStatutoryReceipt.source_version == data.source_version,
    ))
    replayed = await replay(existing_source, ignore_request_key=True)
    if replayed is not None:
        return replayed

    prepared = await prepare_payroll_statutory(session, org_id, month, data)
    if prepared["digest"] != data.digest:
        raise AccountingError("Payroll statutory posting changed; review it again")
    if prepared["source_digest"] != data.source_digest:
        raise AccountingError("Payroll statutory source changed; review it again")
    entry = await service.post(
        session, org_id, PostingInput.model_validate(prepared["posting_document"]),
        actor, event_bus, payroll_statutory_import=True,
    )
    session.add(PayrollStatutoryReceipt(
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


async def payroll_statutory_result(session, org_id: int, request_key: UUID):
    return await session.scalar(select(PayrollStatutoryReceipt).where(
        PayrollStatutoryReceipt.organization_id == org_id,
        PayrollStatutoryReceipt.request_key == str(request_key),
    ))
