"""Append-only source review of employer payroll rules, without rate certification."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, timedelta
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import Field, ValidationError, field_validator, model_validator
from sqlalchemy import select

from modules.accounting.models import PayrollOrganizationReview, Period
from modules.accounting.payroll_applicability import ORGANIZATION_RULE_CODES
from modules.accounting.payroll_evidence_files import file_for
from modules.accounting.schemas import Input, Money
from modules.accounting.service import AccountingError, audit, lock_organization


def _digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    ).encode()).hexdigest()


class ReviewedRule(Input):
    code: str = Field(min_length=1, max_length=80)
    decision: Literal["applicable", "not_applicable", "unresolved"]
    finding: str = Field(min_length=10, max_length=500)
    source_locator: str = Field(min_length=3, max_length=200)
    reference_wage_month: str | None = Field(
        default=None, pattern=r"^[0-9]{4}-(0[1-9]|1[0-2])$",
    )
    reference_wage_byn: Money | None = Field(default=None, gt=0)
    reference_wage_published_on: date | None = None
    reference_wage_url: str | None = Field(
        default=None, max_length=500,
        pattern=r"^https://(?:www\.)?belstat\.gov\.by/[^\s#]+$",
    )
    minimum_wage_month: str | None = Field(
        default=None, pattern=r"^[0-9]{4}-(0[1-9]|1[0-2])$",
    )
    minimum_wage_byn: Money | None = Field(default=None, gt=0)
    minimum_wage_published_on: date | None = None
    minimum_wage_url: str | None = Field(
        default=None, max_length=500,
        pattern=r"^https://(?:www\.)?(?:nalog|mintrud)\.gov\.by/[^\s#]+$",
    )
    minimum_wage_source_file_id: int | None = Field(default=None, gt=0, strict=True)
    minimum_wage_source_file_sha256: str | None = Field(
        default=None, pattern=r"^[a-f0-9]{64}$",
    )
    minimum_wage_source_locator: str | None = Field(default=None, min_length=3, max_length=200)

    @field_validator("reference_wage_byn", "minimum_wage_byn", mode="before")
    @classmethod
    def exact_reference_wage(cls, value):
        if value is not None and (not isinstance(value, str)
                                  or re.fullmatch(r"\d{1,17}\.\d{2}", value) is None):
            raise ValueError("Reference wage must be a two-decimal BYN string")
        return value

    @model_validator(mode="after")
    def reference_wage_is_one_fszn_fact(self):
        values = (self.reference_wage_month, self.reference_wage_byn,
                  self.reference_wage_published_on, self.reference_wage_url)
        if any(value is not None for value in values):
            if (not all(value is not None for value in values)
                    or self.code != "period_fszn_rules_and_limits"
                    or self.decision != "applicable"):
                raise ValueError("Reference wage needs one applicable FSZN fact and complete source")
        minimum = (self.minimum_wage_month, self.minimum_wage_byn,
                   self.minimum_wage_published_on, self.minimum_wage_url,
                   self.minimum_wage_source_file_id,
                   self.minimum_wage_source_file_sha256,
                   self.minimum_wage_source_locator)
        if any(value is not None for value in minimum):
            if (not all(value is not None for value in minimum)
                    or self.code != "period_fszn_rules_and_limits"
                    or self.decision != "applicable"):
                raise ValueError("Minimum wage needs one applicable FSZN fact and complete source")
        return self

    @field_validator("code")
    @classmethod
    def allowed_code(cls, value: str) -> str:
        if value not in ORGANIZATION_RULE_CODES:
            raise ValueError("Unsupported employer payroll rule")
        return value

    @field_validator("finding", "source_locator")
    @classmethod
    def meaningful_text(cls, value: str) -> str:
        if not value.strip() or "\x00" in value:
            raise ValueError("Employer payroll rule evidence must be nonempty")
        return value.strip()

    @field_validator("minimum_wage_source_locator")
    @classmethod
    def meaningful_minimum_locator(cls, value: str | None) -> str | None:
        return cls.meaningful_text(value) if value is not None else None


class PayrollOrganizationInput(Input):
    request_key: UUID
    source_file_id: int = Field(gt=0, strict=True)
    source_document: str = Field(min_length=1, max_length=160)
    facts: list[ReviewedRule] = Field(min_length=1, max_length=len(ORGANIZATION_RULE_CODES))
    evidence: str = Field(min_length=10, max_length=2000)
    supersedes_id: int | None = Field(default=None, gt=0, strict=True)

    @field_validator("facts")
    @classmethod
    def unique_sorted_facts(cls, value: list[ReviewedRule]) -> list[ReviewedRule]:
        codes = [item.code for item in value]
        if codes != sorted(set(codes)):
            raise ValueError("Employer payroll rules must be unique and sorted by code")
        return value

    @field_validator("source_document", "evidence")
    @classmethod
    def meaningful_source(cls, value: str) -> str:
        if not value.strip() or "\x00" in value:
            raise ValueError("Employer payroll rule source must be nonempty")
        return value.strip()


def result(row: PayrollOrganizationReview) -> dict:
    snapshot = {
        "organization_id": row.organization_id,
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
        "request_key", "source_file_id", "source_document", "facts", "evidence", "supersedes_id",
    )}
    if (row.snapshot != snapshot or row.digest != _digest(snapshot)
            or row.request_digest != _digest(command)):
        raise HTTPException(409, "Employer payroll rule review integrity requires reconciliation")
    previous_month = (date.fromisoformat(row.month + "-01")
                      - timedelta(days=1)).strftime("%Y-%m")
    try:
        parsed_facts = [ReviewedRule.model_validate(fact) for fact in row.facts]
    except (ValidationError, TypeError) as exc:
        raise HTTPException(409, "Employer payroll rule facts require reconciliation") from exc
    if any(fact.reference_wage_month is not None
           and fact.reference_wage_month != previous_month for fact in parsed_facts):
        raise HTTPException(409, "FSZN reference wage month requires reconciliation")
    if any(fact.minimum_wage_month is not None
           and fact.minimum_wage_month != row.month for fact in parsed_facts):
        raise HTTPException(409, "FSZN minimum wage month requires reconciliation")
    return {
        "review_id": row.id, **snapshot, "digest": row.digest, "actor": row.actor,
        "source_file_bytes_verified_now": False,
        "fact_findings_verified_by_software": False,
        "statutory_payroll_certified": False,
        "posting_available": False,
    }


async def latest(session, org_id: int, month: str) -> PayrollOrganizationReview | None:
    return await session.scalar(select(PayrollOrganizationReview).where(
        PayrollOrganizationReview.organization_id == org_id,
        PayrollOrganizationReview.month == month,
    ).order_by(PayrollOrganizationReview.revision.desc()).limit(1))


async def by_request(session, org_id: int, request_key: UUID) -> dict:
    row = await session.scalar(select(PayrollOrganizationReview).where(
        PayrollOrganizationReview.organization_id == org_id,
        PayrollOrganizationReview.request_key == str(request_key),
    ))
    if row is None:
        raise HTTPException(404, "Employer payroll rule review request was not found")
    return result(row)


async def current_for(session, org_id: int, month: str) -> dict | None:
    """Check every revision and the current private source bytes."""
    rows = (await session.scalars(select(PayrollOrganizationReview).where(
        PayrollOrganizationReview.organization_id == org_id,
        PayrollOrganizationReview.month == month,
    ).order_by(PayrollOrganizationReview.revision))).all()
    if not rows:
        return None
    prior = None
    for row in rows:
        result(row)
        if (row.revision != (prior.revision + 1 if prior else 1)
                or row.supersedes_id != (prior.id if prior else None)):
            raise HTTPException(409, "Employer payroll rule review chain requires reconciliation")
        prior = row
    row = rows[-1]
    source = await file_for(session, org_id, row.source_file_id,
                            kind="payroll_organization_rule", month=month)
    if (source.employment_binding_id is not None
            or source.sha256 != row.source_file_sha256
            or source.reference != row.source_document):
        raise HTTPException(409, "Employer payroll rule source file changed")
    reviewed = [fact["code"] for fact in row.facts if fact["decision"] != "unresolved"]
    unresolved = [code for code in ORGANIZATION_RULE_CODES if code not in reviewed]
    reference_wage = next((fact for fact in row.facts if
                           fact["code"] == "period_fszn_rules_and_limits"
                           and fact.get("reference_wage_byn") is not None), None)
    current = {
        "review_id": row.id, "review_digest": row.digest,
        "reviewed_rule_codes": reviewed,
        "unresolved_rule_codes": unresolved,
        "rule_decisions": {fact["code"]: fact["decision"] for fact in row.facts},
    }
    if reference_wage:
        current["fszn_reference_wage"] = {
            "wage_month": reference_wage["reference_wage_month"],
            "wage_byn": reference_wage["reference_wage_byn"],
            "published_on": reference_wage["reference_wage_published_on"],
            "url": reference_wage["reference_wage_url"],
            "source_file_id": row.source_file_id,
            "source_file_sha256": row.source_file_sha256,
        }
    minimum_wage = next((fact for fact in row.facts if
                         fact["code"] == "period_fszn_rules_and_limits"
                         and fact.get("minimum_wage_byn") is not None), None)
    if minimum_wage:
        minimum_file = await file_for(
            session, org_id, minimum_wage["minimum_wage_source_file_id"],
            kind="payroll_organization_rule", month=month,
        )
        if (minimum_file.employment_binding_id is not None
                or minimum_file.sha256 != minimum_wage["minimum_wage_source_file_sha256"]):
            raise HTTPException(409, "FSZN minimum wage source file changed")
        current["fszn_minimum_wage"] = {
            "wage_month": minimum_wage["minimum_wage_month"],
            "wage_byn": minimum_wage["minimum_wage_byn"],
            "published_on": minimum_wage["minimum_wage_published_on"],
            "url": minimum_wage["minimum_wage_url"],
            "source_file_id": minimum_file.id,
            "source_file_sha256": minimum_file.sha256,
            "source_locator": minimum_wage["minimum_wage_source_locator"],
        }
    return current


async def create(session, org_id: int, month: str, data: PayrollOrganizationInput,
                 actor: str) -> dict:
    await lock_organization(session, org_id)
    command = data.model_dump(mode="json")
    for fact in command["facts"]:
        for field in ("reference_wage_month", "reference_wage_byn",
                      "reference_wage_published_on", "reference_wage_url",
                      "minimum_wage_month", "minimum_wage_byn",
                      "minimum_wage_published_on", "minimum_wage_url",
                      "minimum_wage_source_file_id", "minimum_wage_source_file_sha256",
                      "minimum_wage_source_locator"):
            if fact[field] is None:
                fact.pop(field)  # Preserve old command digests and receipts.
        if "reference_wage_month" in fact:
            previous_month = (date.fromisoformat(month + "-01")
                              - timedelta(days=1)).strftime("%Y-%m")
            if fact["reference_wage_month"] != previous_month:
                raise AccountingError("FSZN reference wage must be from the preceding month")
        if "minimum_wage_month" in fact:
            if fact["minimum_wage_month"] != month:
                raise AccountingError("FSZN minimum wage must be for the payroll month")
            minimum_file = await file_for(
                session, org_id, fact["minimum_wage_source_file_id"],
                kind="payroll_organization_rule", month=month,
            )
            if (minimum_file.employment_binding_id is not None
                    or minimum_file.sha256 != fact["minimum_wage_source_file_sha256"]):
                raise AccountingError("FSZN minimum wage source differs from stored file")
    request_digest = _digest(command)
    existing = await session.scalar(select(PayrollOrganizationReview).where(
        PayrollOrganizationReview.organization_id == org_id,
        PayrollOrganizationReview.request_key == str(data.request_key),
    ))
    if existing is not None:
        if existing.request_digest != request_digest or existing.month != month:
            raise HTTPException(409, "Employer payroll rule request key was reused with different content")
        source = await file_for(session, org_id, existing.source_file_id,
                                kind="payroll_organization_rule", month=month)
        if source.employment_binding_id is not None or source.sha256 != existing.source_file_sha256:
            raise HTTPException(409, "Employer payroll rule source file changed")
        return result(existing)

    closed = await session.scalar(select(Period.id).where(
        Period.organization_id == org_id, Period.month >= month,
        Period.closed.is_(True),
    ).limit(1))
    if closed is not None:
        raise AccountingError("Closed period blocks a new employer payroll rule review")
    source = await file_for(session, org_id, data.source_file_id,
                            kind="payroll_organization_rule", month=month)
    if source.employment_binding_id is not None or source.reference != data.source_document:
        raise AccountingError("Employer payroll rule source differs from the stored organization file")
    prior = await latest(session, org_id, month)
    if data.supersedes_id != (prior.id if prior else None):
        raise AccountingError("Employer payroll rule revision must supersede the latest review")
    revision = prior.revision + 1 if prior else 1
    snapshot = {
        "organization_id": org_id, "month": month,
        "revision": revision, "supersedes_id": data.supersedes_id,
        "source_file_id": source.id, "source_file_sha256": source.sha256,
        "source_document": source.reference, "facts": command["facts"],
        "evidence": data.evidence, "request_key": str(data.request_key),
    }
    row = PayrollOrganizationReview(
        **snapshot, request_digest=request_digest,
        digest=_digest(snapshot), snapshot=snapshot, actor=actor,
    )
    session.add(row)
    await session.flush()
    audit(session, org_id, actor, "payroll_organization_rule_reviewed", {
        "month": month, "review_id": row.id, "revision": revision,
        "source_file_id": source.id,
        "recorded_rule_codes": [fact["code"] for fact in command["facts"]],
    })
    return result(row)
