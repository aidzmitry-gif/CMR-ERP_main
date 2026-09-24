"""Chief-reviewed employee applicability facts, scoped to one payroll month."""
from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import Field, ValidationError, field_validator, model_validator
from sqlalchemy import select

from modules.accounting.models import PayrollApplicabilityReview, Period
from modules.accounting.payroll_applicability import EMPLOYEE_FACT_CODES
from modules.accounting.payroll_evidence_files import file_for
from modules.accounting.payroll_population import known_population
from modules.accounting.schemas import Input
from modules.accounting.service import AccountingError, audit, lock_organization


def _digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    ).encode()).hexdigest()


class ReviewedFact(Input):
    code: str = Field(min_length=1, max_length=80)
    finding: str = Field(min_length=10, max_length=500)
    source_locator: str = Field(min_length=3, max_length=200)
    fszn_minimum_condition: Literal[
        "applies", "excluded_civil_contract", "excluded_correctional_or_ltp",
        "excluded_public_religious", "excluded_employee_fault_norm", "unresolved",
    ] | None = None
    fszn_minimum_full_month_norm_hours: Decimal | None = Field(default=None, gt=0, le=744)
    fszn_minimum_full_norm_locator: str | None = Field(default=None, min_length=3, max_length=200)

    @field_validator("fszn_minimum_full_month_norm_hours", mode="before")
    @classmethod
    def exact_full_norm(cls, value):
        if value is not None and (not isinstance(value, str)
                                  or re.fullmatch(r"\d{1,3}\.\d{2}", value) is None):
            raise ValueError("Full-month norm must be a two-decimal hour string")
        return value

    @model_validator(mode="after")
    def minimum_condition_is_scoped(self):
        if ((self.code == "fszn_minimum_condition") !=
                (self.fszn_minimum_condition is not None)):
            raise ValueError("FSZN minimum decision belongs to its source-backed fact")
        has_norm = (self.fszn_minimum_full_month_norm_hours is not None
                    or self.fszn_minimum_full_norm_locator is not None)
        if self.code == "fszn_minimum_condition" and self.fszn_minimum_condition == "applies":
            if (self.fszn_minimum_full_month_norm_hours is None
                    or self.fszn_minimum_full_norm_locator is None):
                raise ValueError("Applicable FSZN minimum needs sourced full-month norm")
        elif has_norm:
            raise ValueError("Full-month norm belongs only to applicable FSZN minimum")
        return self

    @field_validator("code")
    @classmethod
    def allowed_code(cls, value: str) -> str:
        if value not in EMPLOYEE_FACT_CODES:
            raise ValueError("Unsupported payroll applicability fact")
        return value

    @field_validator("finding", "source_locator")
    @classmethod
    def meaningful_text(cls, value: str) -> str:
        if not value.strip() or "\x00" in value:
            raise ValueError("Payroll applicability evidence must be nonempty")
        return value.strip()

    @field_validator("fszn_minimum_full_norm_locator")
    @classmethod
    def meaningful_norm_locator(cls, value: str | None) -> str | None:
        return cls.meaningful_text(value) if value is not None else None


class PayrollApplicabilityInput(Input):
    request_key: UUID
    employment_binding_id: int = Field(gt=0, strict=True)
    source_file_id: int = Field(gt=0, strict=True)
    source_document: str = Field(min_length=1, max_length=160)
    facts: list[ReviewedFact] = Field(min_length=1, max_length=len(EMPLOYEE_FACT_CODES))
    evidence: str = Field(min_length=10, max_length=2000)
    supersedes_id: int | None = Field(default=None, gt=0, strict=True)

    @field_validator("facts")
    @classmethod
    def unique_sorted_facts(cls, value: list[ReviewedFact]) -> list[ReviewedFact]:
        codes = [item.code for item in value]
        if codes != sorted(set(codes)):
            raise ValueError("Payroll applicability facts must be unique and sorted by code")
        return value

    @field_validator("source_document", "evidence")
    @classmethod
    def meaningful_source(cls, value: str) -> str:
        if not value.strip() or "\x00" in value:
            raise ValueError("Payroll applicability source must be nonempty")
        return value.strip()


def result(row: PayrollApplicabilityReview) -> dict:
    snapshot = {
        "organization_id": row.organization_id,
        "employment_binding_id": row.employment_binding_id,
        "month": row.month,
        "revision": row.revision,
        "supersedes_id": row.supersedes_id,
        "source_file_id": row.source_file_id,
        "source_file_sha256": row.source_file_sha256,
        "source_document": row.source_document,
        "facts": row.facts,
        "evidence": row.evidence,
        "request_key": row.request_key,
    }
    command = {key: snapshot[key] for key in (
        "request_key", "employment_binding_id", "source_file_id",
        "source_document", "facts", "evidence", "supersedes_id",
    )}
    if (row.snapshot != snapshot or row.digest != _digest(snapshot)
            or row.request_digest != _digest(command)):
        raise HTTPException(409, "Payroll applicability review integrity requires reconciliation")
    try:
        [ReviewedFact.model_validate(fact) for fact in row.facts]
    except (ValidationError, TypeError) as exc:
        raise HTTPException(409, "Payroll applicability facts require reconciliation") from exc
    return {
        "review_id": row.id, **snapshot, "digest": row.digest, "actor": row.actor,
        "source_file_bytes_verified_now": False,
        "fact_findings_verified_by_software": False,
        "statutory_payroll_certified": False,
        "posting_available": False,
    }


async def latest(session, org_id: int, month: str,
                 binding_id: int) -> PayrollApplicabilityReview | None:
    return await session.scalar(select(PayrollApplicabilityReview).where(
        PayrollApplicabilityReview.organization_id == org_id,
        PayrollApplicabilityReview.month == month,
        PayrollApplicabilityReview.employment_binding_id == binding_id,
    ).order_by(PayrollApplicabilityReview.revision.desc()).limit(1))


async def by_request(session, org_id: int, request_key: UUID) -> dict:
    row = await session.scalar(select(PayrollApplicabilityReview).where(
        PayrollApplicabilityReview.organization_id == org_id,
        PayrollApplicabilityReview.request_key == str(request_key),
    ))
    if row is None:
        raise HTTPException(404, "Payroll applicability review request was not found")
    return result(row)


async def current_for(session, org_id: int, month: str,
                      binding_ids: list[int]) -> dict[int, dict]:
    """Verify the latest review and current private bytes for each known binding."""
    if not binding_ids:
        return {}
    rows = (await session.scalars(select(PayrollApplicabilityReview).where(
        PayrollApplicabilityReview.organization_id == org_id,
        PayrollApplicabilityReview.month == month,
        PayrollApplicabilityReview.employment_binding_id.in_(binding_ids),
    ).order_by(PayrollApplicabilityReview.employment_binding_id,
               PayrollApplicabilityReview.revision))).all()
    grouped: dict[int, list[PayrollApplicabilityReview]] = {}
    for row in rows:
        grouped.setdefault(row.employment_binding_id, []).append(row)
    current = {}
    for binding_id, history in grouped.items():
        previous = None
        for row in history:
            result(row)
            if (row.revision != (previous.revision + 1 if previous else 1)
                    or row.supersedes_id != (previous.id if previous else None)):
                raise HTTPException(409, "Payroll applicability review chain requires reconciliation")
            previous = row
        row = history[-1]
        source = await file_for(session, org_id, row.source_file_id,
                                kind="payroll_applicability",
                                employment_binding_id=binding_id, month=month)
        if source.sha256 != row.source_file_sha256 or source.reference != row.source_document:
            raise HTTPException(409, "Payroll applicability source file changed")
        current[binding_id] = {
            "review_id": row.id, "digest": row.digest,
            "source_file_id": source.id, "source_file_sha256": source.sha256,
            "reviewed_fact_codes": [fact["code"] for fact in row.facts],
            "fszn_minimum_condition": next((fact["fszn_minimum_condition"]
                for fact in row.facts if fact["code"] == "fszn_minimum_condition"), None),
            "fszn_minimum_full_month_norm_hours": next((fact.get("fszn_minimum_full_month_norm_hours")
                for fact in row.facts if fact["code"] == "fszn_minimum_condition"), None),
            "fszn_minimum_full_norm_locator": next((fact.get("fszn_minimum_full_norm_locator")
                for fact in row.facts if fact["code"] == "fszn_minimum_condition"), None),
            "source_file_bytes_verified_now": True,
        }
    return current


async def create(session, org_id: int, month: str, data: PayrollApplicabilityInput,
                 actor: str) -> dict:
    await lock_organization(session, org_id)
    command = data.model_dump(mode="json")
    for fact in command["facts"]:
        for optional in ("fszn_minimum_condition", "fszn_minimum_full_month_norm_hours",
                         "fszn_minimum_full_norm_locator"):
            if fact[optional] is None:
                fact.pop(optional)  # Keep old receipt digests stable.
    command_digest = _digest(command)
    existing = await session.scalar(select(PayrollApplicabilityReview).where(
        PayrollApplicabilityReview.organization_id == org_id,
        PayrollApplicabilityReview.request_key == str(data.request_key),
    ))
    if existing is not None:
        if (existing.request_digest != command_digest or existing.month != month
                or existing.employment_binding_id != data.employment_binding_id):
            raise HTTPException(409, "Payroll applicability request key was reused with different content")
        source = await file_for(session, org_id, existing.source_file_id,
                                kind="payroll_applicability",
                                employment_binding_id=existing.employment_binding_id,
                                month=month)
        if source.sha256 != existing.source_file_sha256:
            raise HTTPException(409, "Payroll applicability source file changed")
        return result(existing)

    closed = await session.scalar(select(Period.id).where(
        Period.organization_id == org_id, Period.month >= month,
        Period.closed.is_(True),
    ).limit(1))
    if closed is not None:
        raise AccountingError("Closed period blocks a new payroll applicability review")
    binding_ids, _ = await known_population(session, org_id, month)
    if data.employment_binding_id not in binding_ids:
        raise AccountingError("Payroll applicability review needs an active binding of this organization")
    source = await file_for(session, org_id, data.source_file_id,
                            kind="payroll_applicability",
                            employment_binding_id=data.employment_binding_id, month=month)
    if source.reference != data.source_document:
        raise AccountingError("Payroll applicability source document differs from stored file")
    prior = await latest(session, org_id, month, data.employment_binding_id)
    if data.supersedes_id != (prior.id if prior else None):
        raise AccountingError("Payroll applicability revision must supersede the latest review")
    revision = prior.revision + 1 if prior else 1
    snapshot = {
        "organization_id": org_id, "employment_binding_id": data.employment_binding_id,
        "month": month, "revision": revision, "supersedes_id": data.supersedes_id,
        "source_file_id": source.id, "source_file_sha256": source.sha256,
        "source_document": source.reference, "facts": command["facts"],
        "evidence": data.evidence, "request_key": str(data.request_key),
    }
    row = PayrollApplicabilityReview(
        **snapshot, request_digest=command_digest,
        digest=_digest(snapshot), snapshot=snapshot, actor=actor,
    )
    session.add(row)
    await session.flush()
    audit(session, org_id, actor, "payroll_applicability_reviewed", {
        "month": month, "employment_binding_id": data.employment_binding_id,
        "review_id": row.id, "revision": revision, "source_file_id": source.id,
        "reviewed_fact_codes": [fact["code"] for fact in command["facts"]],
    })
    return result(row)
