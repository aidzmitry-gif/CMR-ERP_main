"""Append-only source review of employer payroll rules, without rate certification."""
from __future__ import annotations

import hashlib
import json
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import Field, field_validator
from sqlalchemy import select

from modules.accounting.models import PayrollOrganizationReview, Period
from modules.accounting.payroll_applicability import ORGANIZATION_RULE_CODES
from modules.accounting.payroll_evidence_files import file_for
from modules.accounting.schemas import Input
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
    return {
        "review_id": row.id, "review_digest": row.digest,
        "reviewed_rule_codes": reviewed,
        "unresolved_rule_codes": unresolved,
        "rule_decisions": {fact["code"]: fact["decision"] for fact in row.facts},
    }


async def create(session, org_id: int, month: str, data: PayrollOrganizationInput,
                 actor: str) -> dict:
    await lock_organization(session, org_id)
    command = data.model_dump(mode="json")
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
