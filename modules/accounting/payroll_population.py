"""Chief-attested monthly payroll roster; source facts remain human-reviewed."""
from __future__ import annotations

import hashlib
import json
from uuid import UUID

from fastapi import HTTPException
from pydantic import Field, field_validator
from sqlalchemy import select

from modules.accounting.models import PayrollEmploymentBinding, PayrollPopulationReview, Period
from modules.accounting.payroll_evidence_files import file_for
from modules.accounting.payroll_workpaper_review import _known_binding_coverage
from modules.accounting.schemas import Input
from modules.accounting.service import AccountingError, audit, lock_organization


def _digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    ).encode()).hexdigest()


class PayrollPopulationInput(Input):
    request_key: UUID
    source_file_id: int = Field(gt=0, strict=True)
    source_system: str = Field(min_length=1, max_length=80)
    source_document: str = Field(min_length=1, max_length=160)
    source_employee_count: int = Field(ge=0, strict=True)
    binding_ids: list[int] = Field(max_length=10000)
    employee_ids: list[int] = Field(max_length=10000)
    evidence: str = Field(min_length=10, max_length=2000)
    supersedes_id: int | None = Field(default=None, gt=0, strict=True)

    @field_validator("binding_ids", "employee_ids")
    @classmethod
    def sorted_ids(cls, value: list[int]) -> list[int]:
        if any(type(item) is not int or item <= 0 for item in value) or value != sorted(set(value)):
            raise ValueError("Payroll roster IDs must be positive, unique and sorted")
        return value

    @field_validator("source_system", "source_document", "evidence")
    @classmethod
    def source_text(cls, value: str) -> str:
        if not value.strip() or "\x00" in value:
            raise ValueError("Payroll roster source text must be nonempty")
        return value


async def known_population(session, org_id: int, month: str) -> tuple[list[int], list[int]]:
    coverage = await _known_binding_coverage(session, org_id, month, {})
    binding_ids = sorted(item["employment_binding_id"] for item in coverage["expected_intervals"])
    if not binding_ids:
        return [], []
    rows = (await session.scalars(select(PayrollEmploymentBinding).where(
        PayrollEmploymentBinding.organization_id == org_id,
        PayrollEmploymentBinding.id.in_(binding_ids),
    ))).all()
    if len(rows) != len(binding_ids):
        raise HTTPException(409, "Known payroll employment roster requires reconciliation")
    return binding_ids, sorted({row.employee_id for row in rows})


def result(row: PayrollPopulationReview) -> dict:
    snapshot = {
        "organization_id": row.organization_id,
        "month": row.month,
        "revision": row.revision,
        "supersedes_id": row.supersedes_id,
        "source_file_id": row.source_file_id,
        "source_file_sha256": row.source_file_sha256,
        "source_system": row.source_system,
        "source_document": row.source_document,
        "source_employee_count": row.source_employee_count,
        "binding_ids": row.binding_ids,
        "employee_ids": row.employee_ids,
        "evidence": row.evidence,
        "request_key": row.request_key,
    }
    command = {key: snapshot[key] for key in (
        "request_key", "source_file_id", "source_system", "source_document",
        "source_employee_count", "binding_ids", "employee_ids", "evidence", "supersedes_id",
    )}
    if (row.snapshot != snapshot or row.digest != _digest(snapshot)
            or row.request_digest != _digest(command)):
        raise HTTPException(409, "Payroll population review integrity requires reconciliation")
    return {
        "review_id": row.id, **snapshot, "digest": row.digest, "actor": row.actor,
        "source_file_bytes_verified_now": False,
        "source_facts_verified_by_software": False,
        "complete_employee_population_proven": False,
        "statutory_payroll_certified": False,
    }


async def latest(session, org_id: int, month: str) -> PayrollPopulationReview | None:
    return await session.scalar(select(PayrollPopulationReview).where(
        PayrollPopulationReview.organization_id == org_id,
        PayrollPopulationReview.month == month,
    ).order_by(PayrollPopulationReview.revision.desc()).limit(1))


async def state(session, org_id: int, month: str) -> dict:
    binding_ids, employee_ids = await known_population(session, org_id, month)
    row = await latest(session, org_id, month)
    review = result(row) if row else None
    return {
        "known_binding_ids": binding_ids,
        "known_employee_ids": employee_ids,
        "review": review,
        "matches_current_bindings": bool(
            row and row.binding_ids == binding_ids and row.employee_ids == employee_ids
            and row.source_employee_count == len(employee_ids)
        ),
    }


async def create(session, org_id: int, month: str, data: PayrollPopulationInput,
                 actor: str) -> dict:
    await lock_organization(session, org_id)
    command = data.model_dump(mode="json")
    command_digest = _digest(command)
    existing = await session.scalar(select(PayrollPopulationReview).where(
        PayrollPopulationReview.organization_id == org_id,
        PayrollPopulationReview.request_key == str(data.request_key),
    ))
    if existing is not None:
        if existing.request_digest != command_digest or existing.month != month:
            raise HTTPException(409, "Payroll population request key was reused with different content")
        source_file = await file_for(session, org_id, existing.source_file_id,
                                     kind="payroll_population", month=month)
        if source_file.sha256 != existing.source_file_sha256:
            raise HTTPException(409, "Payroll population source file changed")
        return result(existing)

    closed = await session.scalar(select(Period.id).where(
        Period.organization_id == org_id, Period.month >= month,
        Period.closed.is_(True),
    ).limit(1))
    if closed is not None:
        raise AccountingError("Closed period blocks a new payroll population review")
    source_file = await file_for(session, org_id, data.source_file_id,
                                 kind="payroll_population", month=month)
    if source_file.reference != data.source_document:
        raise AccountingError("Payroll population source document must match the stored file")
    binding_ids, employee_ids = await known_population(session, org_id, month)
    if (data.binding_ids != binding_ids or data.employee_ids != employee_ids
            or data.source_employee_count != len(employee_ids)):
        raise AccountingError("Payroll population declaration differs from known employment bindings")
    prior = await latest(session, org_id, month)
    if data.supersedes_id != (prior.id if prior else None):
        raise AccountingError("Payroll population revision must supersede the latest review")
    revision = prior.revision + 1 if prior else 1
    snapshot = {
        "organization_id": org_id, "month": month, "revision": revision,
        "supersedes_id": data.supersedes_id,
        "source_file_id": source_file.id, "source_file_sha256": source_file.sha256,
        "source_system": data.source_system, "source_document": data.source_document,
        "source_employee_count": data.source_employee_count,
        "binding_ids": binding_ids, "employee_ids": employee_ids,
        "evidence": data.evidence, "request_key": str(data.request_key),
    }
    row = PayrollPopulationReview(
        **snapshot, request_digest=command_digest, digest=_digest(snapshot),
        snapshot=snapshot, actor=actor,
    )
    session.add(row)
    await session.flush()
    audit(session, org_id, actor, "payroll_population_reviewed", {
        "month": month, "review_id": row.id, "revision": revision,
        "known_employees": len(employee_ids), "source_file_id": source_file.id,
    })
    return result(row)


async def verify_for_close(session, org_id: int, month: str) -> dict:
    current = await state(session, org_id, month)
    review = current["review"]
    if review is None or not current["matches_current_bindings"]:
        raise AccountingError("Current payroll population review is required before closing")
    file = await file_for(session, org_id, review["source_file_id"],
                          kind="payroll_population", month=month)
    if file.sha256 != review["source_file_sha256"] or file.reference != review["source_document"]:
        raise HTTPException(409, "Payroll population source file changed")
    return {**current, "review": {**review, "source_file_bytes_verified_now": True}}
