"""Immutable chief-reviewed arithmetic workpapers, without payroll posting."""
from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import Field, field_validator, model_validator
from sqlalchemy import func, select
from starlette.concurrency import run_in_threadpool

from modules.accounting import payroll_evidence_files
from modules.accounting.models import (
    Entry,
    Line,
    PayrollAccrualReceipt,
    PayrollEmploymentBinding,
    PayrollEvidenceFile,
    PayrollStatutoryReceipt,
    PayrollWorkpaperReview,
    Period,
)
from modules.accounting.payroll_calculation import month_bounds
from modules.accounting.payroll_employment import result as employment_result
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


async def _verify_current_review_files(session, row: PayrollWorkpaperReview) -> None:
    """Recheck selected review sources without rewriting its historical receipt."""
    basis = result(row)["snapshot"]["basis"]

    async def check(file_id: object, kind: str, reference: object, digest: object,
                    *, bound: bool = False, monthly: bool = False) -> None:
        if type(file_id) is not int or file_id <= 0:
            raise HTTPException(409, "Payroll arithmetic review source requires reconciliation")
        source = await payroll_evidence_files.file_for(
            session, row.organization_id, file_id, kind=kind,
            employment_binding_id=row.employment_binding_id if bound else None,
            month=row.month if monthly else None,
        )
        if source.reference != reference or source.sha256 != digest:
            raise HTTPException(409, "Payroll arithmetic review source differs from receipt")

    await check(basis.get("rule_set_source_file_id"), "payroll_policy",
                basis.get("rule_set_source_reference"), basis.get("rule_set_source_digest"))
    await check(basis.get("contract_file_id"), "employment_contract",
                basis.get("contract_document"), basis.get("contract_digest"), bound=True)
    await check(basis.get("timesheet_file_id"), "timesheet",
                basis.get("timesheet_document"), basis.get("timesheet_digest"),
                bound=True, monthly=True)
    await check(basis.get("work_schedule_file_id"), "work_schedule",
                basis.get("work_schedule_document"), basis.get("work_schedule_digest"),
                bound=True, monthly=True)
    for component in basis["components"]:
        if component.get("base_mode") == "gross_less_adjustment" or component.get(
                "adjustment_file_id") is not None:
            await check(component.get("adjustment_file_id"), "base_adjustment",
                        component.get("adjustment_document"),
                        component.get("adjustment_file_digest"), bound=True, monthly=True)


class PayrollWorkpaperReviewInput(PayrollWorkpaperInput):
    request_key: UUID
    basis_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    reviewer_evidence: str = Field(min_length=10, max_length=2000)
    supersedes_review_id: int | None = Field(default=None, gt=0, strict=True)
    source_fact_attestation: Literal["contract_salary_time_norm_checked"] | None = None
    source_fact_evidence: str | None = Field(default=None, max_length=2000)
    fszn_base_attestation: Literal["listed_salary_base_checked"] | None = None
    fszn_base_evidence: str | None = Field(default=None, max_length=2000)
    fszn_base_contract_locator: str | None = Field(default=None, max_length=200)

    @field_validator("reviewer_evidence")
    @classmethod
    def meaningful_review_evidence(cls, value: str) -> str:
        if len(value.strip()) < 10:
            raise ValueError("Chief review evidence must have meaningful text")
        return value

    @model_validator(mode="after")
    def paired_source_fact_attestation(self):
        if (self.source_fact_attestation is None) != (self.source_fact_evidence is None):
            raise ValueError("Source fact attestation and its evidence must be supplied together")
        if self.source_fact_evidence is not None and len(self.source_fact_evidence.strip()) < 20:
            raise ValueError("Source fact evidence must identify the checked document locations")
        classification = (self.fszn_base_attestation, self.fszn_base_evidence,
                          self.fszn_base_contract_locator)
        if any(value is not None for value in classification):
            if (not all(value is not None for value in classification)
                    or self.source_fact_attestation is None):
                raise ValueError("FSZN base review needs complete evidence and source fact attestation")
            if (len(self.fszn_base_evidence.strip()) < 20
                    or len(self.fszn_base_contract_locator.strip()) < 3
                    or "\x00" in self.fszn_base_evidence
                    or "\x00" in self.fszn_base_contract_locator):
                raise ValueError("FSZN base evidence must identify the salary and exclusion sources")
        return self


def _digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    ).encode()).hexdigest()


def result(row: PayrollWorkpaperReview) -> dict:
    if _digest(row.snapshot) != row.snapshot_digest:
        raise HTTPException(409, "Payroll arithmetic review integrity requires reconciliation")
    if row.snapshot.get("basis_digest") != row.basis_digest:
        raise HTTPException(409, "Payroll arithmetic review basis differs from receipt")
    attestation = row.snapshot.get("source_fact_attestation")
    if attestation is not None and (not isinstance(attestation, dict)
                                    or attestation.get("scope") != "contract_salary_time_norm_checked"
                                    or not isinstance(attestation.get("evidence"), str)
                                    or len(attestation["evidence"].strip()) < 20):
        raise HTTPException(409, "Payroll source fact attestation requires reconciliation")
    fszn_base = row.snapshot.get("fszn_base_attestation")
    if fszn_base is not None and (
            attestation is None or not isinstance(fszn_base, dict)
            or fszn_base.get("scope") != "listed_salary_base_checked"
            or not isinstance(fszn_base.get("evidence"), str)
            or len(fszn_base["evidence"].strip()) < 20
            or "\x00" in fszn_base["evidence"]
            or not isinstance(fszn_base.get("contract_locator"), str)
            or len(fszn_base["contract_locator"].strip()) < 3
            or "\x00" in fszn_base["contract_locator"]):
        raise HTTPException(409, "Payroll FSZN base attestation requires reconciliation")
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
        "source_facts_attested_by_chief": attestation is not None,
        "fszn_base_classified_by_chief": fszn_base is not None,
        "posting_available": False,
        "statutory_payroll_certified": False,
    }


async def create(session, org_id: int, month: str,
                 data: PayrollWorkpaperReviewInput, actor: str) -> dict:
    await lock_organization(session, org_id)
    command = data.model_dump(mode="json")
    # Preserve request digests of receipts created before these optional fields existed.
    for field in ("source_fact_attestation", "source_fact_evidence",
                  "fszn_base_attestation", "fszn_base_evidence",
                  "fszn_base_contract_locator"):
        if command[field] is None:
            command.pop(field)
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
            or not preview["rule_source_file_bytes_verified"]
            or not preview["schedule_file_bytes_verified"]):
        raise AccountingError("Payroll review requires stored contract, timesheet, schedule and policy files")
    timesheet_file = await payroll_evidence_files.file_for(
        session, org_id, data.timesheet_file_id, kind="timesheet",
        employment_binding_id=data.employment_binding_id, month=month,
    )
    timesheet_check = await run_in_threadpool(
        payroll_evidence_files.timesheet_preflight, timesheet_file)
    if timesheet_check["status"] in {"structure_failed", "uncheckable"}:
        raise AccountingError("XLSX timesheet structure must pass preflight before arithmetic review")
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

    snapshot = dict(preview)
    if data.source_fact_attestation is not None:
        snapshot["source_fact_attestation"] = {
            "scope": data.source_fact_attestation,
            "evidence": data.source_fact_evidence.strip(),
        }
    if data.fszn_base_attestation is not None:
        snapshot["fszn_base_attestation"] = {
            "scope": data.fszn_base_attestation,
            "evidence": data.fszn_base_evidence.strip(),
            "contract_locator": data.fszn_base_contract_locator.strip(),
        }
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
        snapshot_digest=_digest(snapshot),
        snapshot=snapshot,
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


async def _known_binding_coverage(session, org_id: int, month: str,
                                  by_binding: dict[int, dict]) -> dict:
    first, last = month_bounds(month)
    history = (await session.scalars(select(PayrollEmploymentBinding).where(
        PayrollEmploymentBinding.organization_id == org_id,
        PayrollEmploymentBinding.effective_from <= last,
    ).order_by(PayrollEmploymentBinding.employee_id,
               PayrollEmploymentBinding.contract_ref,
               PayrollEmploymentBinding.effective_from,
               PayrollEmploymentBinding.revision))).all()
    events: dict[tuple[int, str], dict[date, PayrollEmploymentBinding]] = {}
    for row in history:
        employment_result(row)
        events.setdefault((row.employee_id, row.contract_ref), {})[row.effective_from] = row

    expected: dict[int, tuple[date, date]] = {}
    for dated in events.values():
        ordered = sorted(dated.items())
        for index, (effective_from, row) in enumerate(ordered):
            if row.state != "active":
                continue
            end = (ordered[index + 1][0] - timedelta(days=1)
                   if index + 1 < len(ordered) else last)
            start = max(first, effective_from)
            end = min(last, end)
            if start <= end:
                expected[row.id] = (start, end)

    issues = []
    for binding_id, (start, end) in sorted(expected.items()):
        cursor = start
        for segment in by_binding.get(binding_id, {}).get("segments", []):
            segment_from = date.fromisoformat(segment["work_from"])
            segment_to = date.fromisoformat(segment["work_to"])
            if segment_from < start or segment_to > end:
                issues.append({"kind": "outside_current_binding", "employment_binding_id": binding_id,
                               "work_from": segment["work_from"], "work_to": segment["work_to"]})
            if segment_to < start or segment_from > end:
                continue
            if segment_from > cursor:
                issues.append({"kind": "unreviewed_interval", "employment_binding_id": binding_id,
                               "work_from": cursor.isoformat(),
                               "work_to": (min(segment_from, end + timedelta(days=1))
                                           - timedelta(days=1)).isoformat()})
            cursor = max(cursor, min(segment_to, end) + timedelta(days=1))
        if cursor <= end:
            issues.append({"kind": "unreviewed_interval", "employment_binding_id": binding_id,
                           "work_from": cursor.isoformat(), "work_to": end.isoformat()})
    for binding_id, binding in sorted(by_binding.items()):
        if binding_id not in expected:
            for segment in binding["segments"]:
                issues.append({"kind": "outside_current_binding", "employment_binding_id": binding_id,
                               "work_from": segment["work_from"], "work_to": segment["work_to"]})
    return {
        "active_binding_count": len(expected),
        "expected_intervals": [
            {"employment_binding_id": binding_id,
             "work_from": start.isoformat(), "work_to": end.isoformat()}
            for binding_id, (start, end) in sorted(expected.items())
        ],
        "known_binding_coverage_complete": bool(expected) and not issues,
        "organization_payroll_population_verified": False,
        "issues": issues,
    }


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
    unattested_review_ids = []
    for (binding_id, work_from, work_to), revisions in sorted(grouped.items()):
        previous = None
        for row, _ in revisions:
            if (row.revision != (previous.revision + 1 if previous else 1)
                    or row.supersedes_id != (previous.id if previous else None)):
                raise HTTPException(409, "Payroll arithmetic review revision chain requires reconciliation")
            previous = row
        row, amounts = revisions[-1]
        await _verify_current_review_files(session, row)
        receipt = result(row)
        attested = receipt["source_facts_attested_by_chief"]
        fszn_classified = receipt["fszn_base_classified_by_chief"]
        if not attested:
            unattested_review_ids.append(row.id)
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
            "source_facts_attested_by_chief": attested,
            "fszn_base_classified_by_chief": fszn_classified,
        })
        selected_receipts.append({"review_id": row.id, "snapshot_digest": row.snapshot_digest})
        for field in AMOUNT_FIELDS:
            binding["totals"][field] += amounts[field]
            totals[field] += amounts[field]

    for binding in by_binding.values():
        binding["totals"] = {field: format(value, ".2f")
                             for field, value in binding["totals"].items()}
    coverage = await _known_binding_coverage(session, org_id, month, by_binding)
    formatted_totals = {field: format(value, ".2f") for field, value in totals.items()}
    selection_digest = _digest(selected_receipts)
    coverage_digest = _digest(coverage)
    return {
        "status": "arithmetic_reviews_aggregate_only",
        "organization_id": org_id,
        "month": month,
        "review_count": len(rows),
        "selected_segment_count": len(selected_receipts),
        "source_fact_attested_segment_count": len(selected_receipts) - len(unattested_review_ids),
        "source_fact_unattested_review_ids": unattested_review_ids,
        "all_selected_source_facts_attested_by_chief": bool(selected_receipts) and not unattested_review_ids,
        "selection_digest": selection_digest,
        "coverage_digest": coverage_digest,
        "summary_digest": _digest({"organization_id": org_id, "month": month,
                                   "selection_digest": selection_digest,
                                   "coverage_digest": coverage_digest,
                                   "totals": formatted_totals}),
        "bindings": list(by_binding.values()),
        "totals": formatted_totals,
        "known_binding_coverage": coverage,
        "current_file_bytes_verified": bool(selected_receipts),
        "coverage_verified": False,
        "source_facts_verified": False,
        "statutory_payroll_certified": False,
        "posting_available": False,
    }


def _import_amount(value: object) -> Decimal:
    if not isinstance(value, str):
        raise HTTPException(409, "Payroll import amount requires reconciliation")
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise HTTPException(409, "Payroll import amount requires reconciliation") from exc
    if (not amount.is_finite() or amount <= 0 or amount >= Decimal("1e18")
            or amount * 100 != (amount * 100).to_integral_value()):
        raise HTTPException(409, "Payroll import amount requires reconciliation")
    return amount


async def external_source_reconciliation(session, org_id: int, month: str) -> dict:
    """Compare reviewed arithmetic with posted imports; never certify payroll."""
    from modules.accounting.payroll_population import (
        state as population_state,
    )
    from modules.accounting.payroll_population import (
        verify_for_close as verify_population_for_close,
    )

    await lock_organization(session, org_id)
    summary = await monthly_arithmetic_summary(session, org_id, month)
    population = await population_state(session, org_id, month)
    if population["matches_current_bindings"]:
        await verify_population_for_close(session, org_id, month)
    first, last = month_bounds(month)
    known_ids = set(population["known_binding_ids"])
    workpaper = {item["employment_binding_id"]: item["totals"]
                 for item in summary["bindings"]}
    fields = ("gross_byn", "listed_employee_deductions_byn",
              "listed_employer_contributions_byn")
    imports: dict[int, dict[str, Decimal]] = {}
    receipts: dict[str, list[int]] = {"gross": [], "statutory": []}
    source_binding_ids: dict[str, set[int]] = {"gross": set(), "statutory": set()}
    unmapped_lines = {"gross": 0, "statutory": 0}
    posting_gaps = {}
    for label, model, operation, source_prefix in (
        ("gross", PayrollAccrualReceipt, "payroll_accrual_import", "payroll:accrual:"),
        ("statutory", PayrollStatutoryReceipt, "payroll_statutory_import", "payroll:statutory:"),
    ):
        rows = (await session.execute(select(model, Entry).join(
            Entry, Entry.id == model.entry_id,
        ).where(
            model.organization_id == org_id, model.month == month,
            Entry.organization_id == org_id, Entry.posting_date >= first,
            Entry.posting_date <= last, Entry.operation == operation,
            Entry.source.like(source_prefix + "%"),
        ).order_by(model.entry_id))).all()
        posting_count = await session.scalar(select(func.count(Entry.id)).where(
            Entry.organization_id == org_id, Entry.posting_date >= first,
            Entry.posting_date <= last, Entry.operation == operation,
            Entry.source.like(source_prefix + "%"),
        )) or 0
        posting_gaps[label] = max(0, int(posting_count) - len(rows))
        for receipt, entry in rows:
            source = receipt.source
            command = receipt.command
            lines = source.get("lines") if isinstance(source, dict) else None
            posting = receipt.posting
            if (entry.digest != receipt.digest or not isinstance(command, dict)
                    or not isinstance(lines, list) or not lines
                    or not isinstance(posting, dict)
                    or lines != command.get("lines")
                    or source.get("organization_id") != org_id
                    or source.get("month") != month
                    or source.get("source_document") != receipt.source_document
                    or source.get("source_version") != receipt.source_version
                    or source.get("source_digest") != receipt.source_digest
                    or command.get("source_document") != receipt.source_document
                    or command.get("source_version") != receipt.source_version
                    or command.get("source_digest") != receipt.source_digest
                    or command.get("policy_id") != entry.policy_id
                    or entry.source != f"{source_prefix}{org_id}:{receipt.source_document}"
                    or entry.source_version != receipt.source_version
                    or _digest(posting) != receipt.digest):
                raise HTTPException(409, "Payroll import receipt requires reconciliation")
            posted_lines = (await session.scalars(select(Line).where(
                Line.entry_id == entry.id,
            ).order_by(Line.id))).all()
            posting_lines = posting.get("lines")
            if (not isinstance(posting_lines, list)
                    or len(posted_lines) != len(posting_lines)
                    or len(posted_lines) != 2 * len(lines)):
                raise HTTPException(409, "Payroll import ledger lines require reconciliation")
            for posted, planned in zip(posted_lines, posting_lines, strict=True):
                if (not isinstance(planned, dict) or posted.account_code != planned.get("account")
                        or posted.side != planned.get("side")
                        or posted.amount != _import_amount(planned.get("amount"))
                        or posted.dimensions != planned.get("dimensions")):
                    raise HTTPException(409, "Payroll import ledger lines require reconciliation")
            receipts[label].append(receipt.entry_id)
            source_total = Decimal("0")
            for line in lines:
                if not isinstance(line, dict):
                    raise HTTPException(409, "Payroll import line requires reconciliation")
                amount = _import_amount(line.get("amount_byn"))
                source_total += amount
                binding_id = line.get("employment_binding_id")
                if type(binding_id) is not int or binding_id <= 0:
                    unmapped_lines[label] += 1
                    continue
                source_binding_ids[label].add(binding_id)
                if label == "gross":
                    field = "gross_byn"
                elif line.get("kind") == "employee_deduction":
                    field = "listed_employee_deductions_byn"
                elif line.get("kind") == "employer_contribution":
                    field = "listed_employer_contributions_byn"
                else:
                    raise HTTPException(409, "Payroll statutory line kind requires reconciliation")
                totals = imports.setdefault(binding_id, {key: Decimal("0") for key in fields})
                totals[field] += amount
            if (sum((line.amount for line in posted_lines if line.side == "debit"), Decimal("0"))
                    != source_total or
                    sum((line.amount for line in posted_lines if line.side == "credit"), Decimal("0"))
                    != source_total):
                raise HTTPException(409, "Payroll import amount differs from its ledger package")

    from modules.accounting.payroll_evidence_files import file_for

    statutory_zero_rows = (await session.scalars(select(PayrollEvidenceFile).where(
        PayrollEvidenceFile.organization_id == org_id,
        PayrollEvidenceFile.month == month,
        PayrollEvidenceFile.kind == "payroll_stat_zero_person",
    ).order_by(PayrollEvidenceFile.id))).all()
    statutory_zero_ids = {row.employment_binding_id for row in statutory_zero_rows}
    missing_statutory_ids = sorted(
        source_binding_ids["gross"] - source_binding_ids["statutory"] - statutory_zero_ids)
    conflicting_statutory_ids = sorted(source_binding_ids["statutory"] & statutory_zero_ids)
    used_statutory_zero_file_ids = []
    for row in statutory_zero_rows:
        if row.employment_binding_id in source_binding_ids["gross"]:
            await file_for(session, org_id, row.id, kind="payroll_stat_zero_person", month=month,
                           employment_binding_id=row.employment_binding_id)
            used_statutory_zero_file_ids.append(row.id)

    rows = []
    differences = 0
    for binding_id in sorted(known_ids | set(workpaper) | set(imports)):
        reviewed = workpaper.get(binding_id)
        imported = imports.get(binding_id, {key: Decimal("0") for key in fields})
        deltas = {key: format(imported[key] - Decimal(reviewed[key]), ".2f")
                  for key in fields} if reviewed else None
        if deltas and any(Decimal(value) != 0 for value in deltas.values()):
            differences += 1
        rows.append({
            "employment_binding_id": binding_id,
            "known_active": binding_id in known_ids,
            "reviewed": {key: reviewed[key] for key in fields} if reviewed else None,
            "imported": {key: format(imported[key], ".2f") for key in fields},
            "difference_import_less_review": deltas,
        })
    missing_gross_ids = sorted(known_ids - {
        binding_id for binding_id, amounts in imports.items()
        if amounts["gross_byn"] > 0
    })
    unmatched_import_ids = sorted(set(imports) - set(workpaper))
    ready = bool(
        known_ids and population["matches_current_bindings"]
        and summary["known_binding_coverage"]["known_binding_coverage_complete"]
        and receipts["gross"] and receipts["statutory"]
        and not missing_gross_ids and not unmatched_import_ids
        and not missing_statutory_ids and not conflicting_statutory_ids
        and not any(unmapped_lines.values())
        and not any(posting_gaps.values())
    )
    return {
        "organization_id": org_id, "month": month,
        "status": ("not_ready" if not ready else
                   "differences" if differences else "matched_arithmetic_only"),
        "population_review_current": population["matches_current_bindings"],
        "workpaper_summary_digest": summary["summary_digest"],
        "known_workpaper_coverage_complete": summary["known_binding_coverage"][
            "known_binding_coverage_complete"],
        "receipt_entry_ids": receipts, "receipt_gaps": posting_gaps,
        "unmapped_source_lines": unmapped_lines,
        "missing_gross_binding_ids": missing_gross_ids,
        "missing_statutory_binding_ids": missing_statutory_ids,
        "conflicting_statutory_zero_binding_ids": conflicting_statutory_ids,
        "statutory_person_zero_file_ids": used_statutory_zero_file_ids,
        "unmatched_import_binding_ids": unmatched_import_ids,
        "comparison_ready": ready,
        "differing_binding_count": differences,
        "bindings": rows,
        "current_file_bytes_verified": summary["current_file_bytes_verified"],
        "source_facts_verified": False,
        "statutory_payroll_certified": False,
        "posting_available": False,
    }
