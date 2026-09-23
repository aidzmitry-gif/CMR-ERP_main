"""Immutable chief-reviewed arithmetic workpapers, without payroll posting."""
from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal, InvalidOperation
from uuid import UUID

from fastapi import HTTPException
from pydantic import Field, field_validator
from sqlalchemy import select

from modules.accounting.models import PayrollWorkpaperReview, Period
from modules.accounting.payroll_workpaper import PayrollWorkpaperInput, preview_workpaper
from modules.accounting.service import AccountingError, lock_organization

AMOUNT_FIELDS = (
    "gross_byn", "listed_employee_deductions_byn", "after_listed_deductions_byn",
    "listed_employer_contributions_byn", "cost_including_listed_contributions_byn",
)


def _amount(value: object) -> Decimal:
    if not isinstance(value, str):
        raise HTTPException(409, "Payroll arithmetic review amount requires reconciliation")
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise HTTPException(409, "Payroll arithmetic review amount requires reconciliation") from exc
    if not amount.is_finite() or amount < 0 or format(amount, ".2f") != value:
        raise HTTPException(409, "Payroll arithmetic review amount requires reconciliation")
    return amount


def _review_amounts(row: PayrollWorkpaperReview) -> dict[str, Decimal]:
    receipt = result(row)
    snapshot = receipt["snapshot"]
    basis = snapshot.get("basis")
    if (snapshot.get("status") != "arithmetic_workpaper_only"
            or snapshot.get("posting_available") is not False
            or snapshot.get("statutory_payroll_certified") is not False
            or not isinstance(basis, dict)
            or basis.get("organization_id") != row.organization_id
            or basis.get("employment_binding_id") != row.employment_binding_id
            or basis.get("month") != row.month
            or basis.get("work_from") != row.work_from.isoformat()
            or basis.get("work_to") != row.work_to.isoformat()):
        raise HTTPException(409, "Payroll arithmetic review scope requires reconciliation")
    amounts = {field: _amount(snapshot.get(field)) for field in AMOUNT_FIELDS}
    if (amounts["gross_byn"] - amounts["listed_employee_deductions_byn"]
            != amounts["after_listed_deductions_byn"]):
        raise HTTPException(409, "Payroll arithmetic review totals require reconciliation")
    if (amounts["gross_byn"] + amounts["listed_employer_contributions_byn"]
            != amounts["cost_including_listed_contributions_byn"]):
        raise HTTPException(409, "Payroll arithmetic review totals require reconciliation")
    components = basis.get("components")
    if not isinstance(components, list) or not components:
        raise HTTPException(409, "Payroll arithmetic review components require reconciliation")
    deductions = Decimal("0")
    contributions = Decimal("0")
    for component in components:
        if not isinstance(component, dict) or component.get("role") not in {
                "employee_deduction", "employer_contribution"}:
            raise HTTPException(409, "Payroll arithmetic review components require reconciliation")
        if not isinstance(component.get("rate_code"), str) or not component["rate_code"]:
            raise HTTPException(409, "Payroll arithmetic review components require reconciliation")
        amount = _amount(component.get("amount_byn"))
        if component["role"] == "employee_deduction":
            deductions += amount
        else:
            contributions += amount
    if (deductions != amounts["listed_employee_deductions_byn"]
            or contributions != amounts["listed_employer_contributions_byn"]):
        raise HTTPException(409, "Payroll arithmetic review components require reconciliation")
    return amounts


class PayrollWorkpaperReviewInput(PayrollWorkpaperInput):
    request_key: UUID
    basis_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    reviewer_evidence: str = Field(min_length=10, max_length=2000)
    supersedes_review_id: int | None = Field(default=None, gt=0, strict=True)

    @field_validator("reviewer_evidence")
    @classmethod
    def meaningful_review_evidence(cls, value: str) -> str:
        if len(value.strip()) < 10:
            raise ValueError("Chief review evidence must have meaningful text")
        return value


def _digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    ).encode()).hexdigest()


def result(row: PayrollWorkpaperReview) -> dict:
    if _digest(row.snapshot) != row.snapshot_digest:
        raise HTTPException(409, "Payroll arithmetic review integrity requires reconciliation")
    if row.snapshot.get("basis_digest") != row.basis_digest:
        raise HTTPException(409, "Payroll arithmetic review basis differs from receipt")
    return {
        "review_id": row.id,
        "organization_id": row.organization_id,
        "employment_binding_id": row.employment_binding_id,
        "month": row.month,
        "work_from": row.work_from.isoformat(),
        "work_to": row.work_to.isoformat(),
        "revision": row.revision,
        "supersedes_review_id": row.supersedes_id,
        "request_key": row.request_key,
        "basis_digest": row.basis_digest,
        "snapshot_digest": row.snapshot_digest,
        "reviewer_evidence": row.reviewer_evidence,
        "reviewed_by": row.actor,
        "snapshot": row.snapshot,
        "status": "arithmetic_review_only",
        "bytes_verified_at_review": True,
        "current_file_bytes_verified": False,
        "posting_available": False,
        "statutory_payroll_certified": False,
    }


async def create(session, org_id: int, month: str,
                 data: PayrollWorkpaperReviewInput, actor: str) -> dict:
    await lock_organization(session, org_id)
    command = data.model_dump(mode="json")
    request_digest = _digest(command)
    existing = await session.scalar(select(PayrollWorkpaperReview).where(
        PayrollWorkpaperReview.organization_id == org_id,
        PayrollWorkpaperReview.request_key == str(data.request_key),
    ))
    if existing is not None:
        if existing.request_digest != request_digest or existing.month != month:
            raise HTTPException(409, "Payroll review request key was reused with different content")
        return result(existing)

    closed = await session.scalar(select(Period.id).where(
        Period.organization_id == org_id,
        Period.month >= month,
        Period.closed.is_(True),
    ).limit(1))
    if closed is not None:
        raise AccountingError("Closed period blocks a new payroll arithmetic review")
    preview = await preview_workpaper(session, org_id, month, data)
    if preview["basis_digest"] != data.basis_digest:
        raise AccountingError("Payroll workpaper changed; review the current preview")
    if (not preview["contract_and_timesheet_hashes_verified"]
            or not preview["rule_source_file_bytes_verified"]):
        raise AccountingError("Payroll review requires stored contract, timesheet and policy files")
    if any(component["base_mode"] == "gross_less_adjustment"
           and component["adjustment_file_id"] is None
           for component in preview["basis"]["components"]):
        raise AccountingError("Every adjusted rate base needs its stored source file")

    overlapping = await session.scalar(select(PayrollWorkpaperReview.id).where(
        PayrollWorkpaperReview.organization_id == org_id,
        PayrollWorkpaperReview.employment_binding_id == data.employment_binding_id,
        PayrollWorkpaperReview.month == month,
        PayrollWorkpaperReview.work_from <= data.work_to,
        PayrollWorkpaperReview.work_to >= data.work_from,
        (PayrollWorkpaperReview.work_from != data.work_from)
        | (PayrollWorkpaperReview.work_to != data.work_to),
    ).limit(1))
    if overlapping is not None:
        raise AccountingError("Payroll arithmetic review overlaps another work segment")

    latest = await session.scalar(select(PayrollWorkpaperReview).where(
        PayrollWorkpaperReview.organization_id == org_id,
        PayrollWorkpaperReview.employment_binding_id == data.employment_binding_id,
        PayrollWorkpaperReview.month == month,
        PayrollWorkpaperReview.work_from == data.work_from,
        PayrollWorkpaperReview.work_to == data.work_to,
    ).order_by(PayrollWorkpaperReview.revision.desc()).limit(1))
    if latest is None:
        if data.supersedes_review_id is not None:
            raise AccountingError("First payroll review cannot supersede another receipt")
        revision = 1
    else:
        if data.supersedes_review_id != latest.id:
            raise AccountingError("Payroll review correction must supersede the latest receipt")
        revision = latest.revision + 1

    row = PayrollWorkpaperReview(
        organization_id=org_id,
        employment_binding_id=data.employment_binding_id,
        month=month,
        work_from=data.work_from,
        work_to=data.work_to,
        revision=revision,
        supersedes_id=data.supersedes_review_id,
        request_key=str(data.request_key),
        request_digest=request_digest,
        basis_digest=data.basis_digest,
        snapshot_digest=_digest(preview),
        snapshot=preview,
        reviewer_evidence=data.reviewer_evidence,
        actor=actor,
    )
    session.add(row)
    await session.flush()
    return result(row)


async def by_request(session, org_id: int, request_key: UUID) -> dict:
    row = await session.scalar(select(PayrollWorkpaperReview).where(
        PayrollWorkpaperReview.organization_id == org_id,
        PayrollWorkpaperReview.request_key == str(request_key),
    ))
    if row is None:
        raise HTTPException(404, "Payroll arithmetic review was not found")
    return result(row)


async def monthly_arithmetic_summary(session, org_id: int, month: str) -> dict:
    """Sum latest reviewed segments only; never assert a complete payroll run."""
    rows = (await session.scalars(select(PayrollWorkpaperReview).where(
        PayrollWorkpaperReview.organization_id == org_id,
        PayrollWorkpaperReview.month == month,
    ).order_by(PayrollWorkpaperReview.employment_binding_id,
               PayrollWorkpaperReview.work_from, PayrollWorkpaperReview.work_to,
               PayrollWorkpaperReview.revision))).all()
    grouped: dict[tuple[int, date, date], list[tuple[PayrollWorkpaperReview, dict[str, Decimal]]]] = {}
    for row in rows:
        amounts = _review_amounts(row)
        key = (row.employment_binding_id, row.work_from, row.work_to)
        grouped.setdefault(key, []).append((row, amounts))

    totals = {field: Decimal("0") for field in AMOUNT_FIELDS}
    by_binding: dict[int, dict] = {}
    selected_receipts = []
    for (binding_id, work_from, work_to), revisions in sorted(grouped.items()):
        previous = None
        for row, _ in revisions:
            if (row.revision != (previous.revision + 1 if previous else 1)
                    or row.supersedes_id != (previous.id if previous else None)):
                raise HTTPException(409, "Payroll arithmetic review revision chain requires reconciliation")
            previous = row
        row, amounts = revisions[-1]
        binding = by_binding.setdefault(binding_id, {
            "employment_binding_id": binding_id,
            "segments": [],
            "totals": {field: Decimal("0") for field in AMOUNT_FIELDS},
        })
        if binding["segments"] and binding["segments"][-1]["work_to"] >= work_from.isoformat():
            raise HTTPException(409, "Payroll arithmetic review segments overlap")
        binding["segments"].append({
            "review_id": row.id,
            "revision": row.revision,
            "work_from": work_from.isoformat(),
            "work_to": work_to.isoformat(),
            "basis_digest": row.basis_digest,
            "snapshot_digest": row.snapshot_digest,
        })
        selected_receipts.append({"review_id": row.id, "snapshot_digest": row.snapshot_digest})
        for field in AMOUNT_FIELDS:
            binding["totals"][field] += amounts[field]
            totals[field] += amounts[field]

    for binding in by_binding.values():
        binding["totals"] = {field: format(value, ".2f")
                             for field, value in binding["totals"].items()}
    return {
        "status": "arithmetic_reviews_aggregate_only",
        "organization_id": org_id,
        "month": month,
        "review_count": len(rows),
        "selected_segment_count": len(selected_receipts),
        "selection_digest": _digest(selected_receipts),
        "bindings": list(by_binding.values()),
        "totals": {field: format(value, ".2f") for field, value in totals.items()},
        "coverage_verified": False,
        "source_facts_verified": False,
        "statutory_payroll_certified": False,
        "posting_available": False,
    }
